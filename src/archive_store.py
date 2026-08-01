"""Compressed, searchable archive storage for SuperText note subtrees."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
import shutil
import tempfile
import uuid
import zipfile

from src.search_index import rtf_to_plain_text


class ArchiveError(Exception):
    """Base error for archive operations."""


class ArchiveConflictError(ArchiveError):
    """Raised when restoring would overwrite an active note."""


@dataclass(frozen=True)
class ArchiveRecord:
    archive_id: str
    original_path: str
    archived_at: str
    note_count: int
    compressed_size: int


@dataclass(frozen=True)
class ArchiveSearchResult:
    archive_id: str
    archived_path: str
    note_path: str
    archived_at: str
    snippet: str


class NoteArchiveStore:
    """Store complete note subtrees as independently restorable ZIP files."""

    ARCHIVE_DIRNAME = ".supertext-archive"
    MANIFEST_NAME = "__supertext_archive_manifest__.json"
    FORMAT_VERSION = 1

    def __init__(self, node_root):
        self.node_root = os.path.abspath(os.path.normpath(node_root))
        self.archive_dir = os.path.join(self.node_root, self.ARCHIVE_DIRNAME)

    def _relative_node_path(self, relative_path):
        normalized = os.path.normpath(relative_path)
        if (
            not relative_path
            or normalized in ("", ".")
            or os.path.isabs(normalized)
            or normalized == os.pardir
            or normalized.startswith(os.pardir + os.sep)
        ):
            raise ArchiveError("The archive path must identify a note in this notebook.")

        full_path = os.path.abspath(os.path.join(self.node_root, normalized))
        try:
            if os.path.commonpath([self.node_root, full_path]) != self.node_root:
                raise ArchiveError("The archive path is outside this notebook.")
        except ValueError as exc:
            raise ArchiveError("The archive path is outside this notebook.") from exc
        return normalized, full_path

    @staticmethod
    def _zip_path(path):
        return path.replace("\\", "/").replace(os.sep, "/")

    @staticmethod
    def _local_path(path):
        return os.path.normpath(path.replace("\\", os.sep).replace("/", os.sep))

    def _manifest_from_zip(self, archive_path):
        try:
            with zipfile.ZipFile(archive_path, "r") as archive:
                manifest = json.loads(
                    archive.read(self.MANIFEST_NAME).decode("utf-8")
                )
        except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
            raise ArchiveError(
                f"Could not read archive {os.path.basename(archive_path)}."
            ) from exc

        if manifest.get("format_version") != self.FORMAT_VERSION:
            raise ArchiveError("This archive uses an unsupported format version.")
        required = {"archive_id", "original_path", "archived_at", "note_paths"}
        if not required.issubset(manifest):
            raise ArchiveError("The archive manifest is incomplete.")
        return manifest

    def _record(self, archive_path, manifest):
        return ArchiveRecord(
            archive_id=manifest["archive_id"],
            original_path=self._local_path(manifest["original_path"]),
            archived_at=manifest["archived_at"],
            note_count=len(manifest["note_paths"]),
            compressed_size=os.path.getsize(archive_path),
        )

    def archive(self, relative_path):
        """Compress a note and its descendants, then remove the active copy."""
        relative_path, node_path = self._relative_node_path(relative_path)
        note_path = node_path + ".rtf"
        if not os.path.isfile(note_path) or not os.path.isdir(node_path):
            raise ArchiveError("The selected note is missing its file or companion folder.")

        os.makedirs(self.archive_dir, exist_ok=True)
        archive_id = uuid.uuid4().hex
        final_path = os.path.join(self.archive_dir, archive_id + ".zip")
        temp_path = final_path + ".tmp"
        archived_at = datetime.now(timezone.utc).isoformat()

        members = [note_path]
        directories = []
        for directory, subdirectories, filenames in os.walk(node_path):
            directories.append(directory)
            members.extend(os.path.join(directory, name) for name in filenames)

        note_paths = sorted(
            os.path.splitext(os.path.relpath(path, self.node_root))[0]
            for path in members
            if path.lower().endswith(".rtf")
        )
        manifest = {
            "format_version": self.FORMAT_VERSION,
            "archive_id": archive_id,
            "original_path": self._zip_path(relative_path),
            "archived_at": archived_at,
            "note_paths": [self._zip_path(path) for path in note_paths],
        }

        try:
            with zipfile.ZipFile(
                temp_path,
                "w",
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=9,
            ) as archive:
                archive.writestr(
                    self.MANIFEST_NAME,
                    json.dumps(manifest, ensure_ascii=False, sort_keys=True),
                )
                for directory in directories:
                    relative_directory = os.path.relpath(directory, self.node_root)
                    archive.writestr(self._zip_path(relative_directory) + "/", b"")
                for member in members:
                    archive.write(
                        member,
                        self._zip_path(os.path.relpath(member, self.node_root)),
                    )

            with zipfile.ZipFile(temp_path, "r") as archive:
                if archive.testzip() is not None:
                    raise ArchiveError("The new archive failed its integrity check.")
                json.loads(archive.read(self.MANIFEST_NAME).decode("utf-8"))
            os.replace(temp_path, final_path)
        except Exception as exc:
            try:
                os.remove(temp_path)
            except OSError:
                pass
            if isinstance(exc, ArchiveError):
                raise
            raise ArchiveError("Could not create the compressed archive.") from exc

        staging_dir = tempfile.mkdtemp(prefix=".archive-", dir=self.archive_dir)
        moved = []
        try:
            staged_note = os.path.join(staging_dir, "note.rtf")
            staged_folder = os.path.join(staging_dir, "node")
            shutil.move(note_path, staged_note)
            moved.append((staged_note, note_path))
            shutil.move(node_path, staged_folder)
            moved.append((staged_folder, node_path))
        except Exception as exc:
            for staged_path, original_path in reversed(moved):
                if os.path.exists(staged_path) and not os.path.exists(original_path):
                    shutil.move(staged_path, original_path)
            try:
                os.remove(final_path)
            except OSError:
                pass
            raise ArchiveError("Could not move the note into the archive.") from exc
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)

        return self._record(final_path, manifest)

    def list_archives(self):
        """Return all readable archives, newest first."""
        if not os.path.isdir(self.archive_dir):
            return []
        records = []
        for filename in os.listdir(self.archive_dir):
            if not filename.lower().endswith(".zip"):
                continue
            archive_path = os.path.join(self.archive_dir, filename)
            try:
                records.append(
                    self._record(archive_path, self._manifest_from_zip(archive_path))
                )
            except ArchiveError:
                continue
        return sorted(records, key=lambda record: record.archived_at, reverse=True)

    @staticmethod
    def _read_rtf(archive, member):
        data = archive.read(member)
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return data.decode(errors="replace")

    @staticmethod
    def _snippet(text, match_start, query_length):
        radius = 70
        start = max(0, match_start - radius)
        finish = min(len(text), match_start + query_length + radius)
        snippet = " ".join(text[start:finish].split())
        if start:
            snippet = "\u2026" + snippet
        if finish < len(text):
            snippet += "\u2026"
        return snippet

    def search(self, query, limit=200):
        """Search note names and visible text inside compressed archives."""
        if limit <= 0:
            return []
        normalized_query = query.casefold()
        results = []

        for record in self.list_archives():
            archive_path = os.path.join(self.archive_dir, record.archive_id + ".zip")
            try:
                manifest = self._manifest_from_zip(archive_path)
                with zipfile.ZipFile(archive_path, "r") as archive:
                    for stored_note_path in manifest["note_paths"]:
                        member = self._zip_path(stored_note_path) + ".rtf"
                        note_path = self._local_path(stored_note_path)
                        try:
                            text = rtf_to_plain_text(self._read_rtf(archive, member))
                        except (KeyError, OSError, ValueError):
                            continue

                        match_start = text.casefold().find(normalized_query)
                        name_matches = normalized_query in note_path.casefold()
                        if normalized_query and match_start < 0 and not name_matches:
                            continue
                        snippet = (
                            self._snippet(text, match_start, len(query))
                            if match_start >= 0 and normalized_query
                            else ""
                        )
                        results.append(
                            ArchiveSearchResult(
                                archive_id=record.archive_id,
                                archived_path=record.original_path,
                                note_path=os.path.normpath(note_path),
                                archived_at=record.archived_at,
                                snippet=snippet,
                            )
                        )
                        if len(results) >= limit:
                            return results
            except (ArchiveError, OSError, zipfile.BadZipFile):
                continue
        return results

    @staticmethod
    def _safe_member_path(staging_dir, member):
        member = member.replace("/", os.sep)
        destination = os.path.abspath(os.path.join(staging_dir, member))
        try:
            if os.path.commonpath([staging_dir, destination]) != staging_dir:
                raise ArchiveError("The archive contains an unsafe path.")
        except ValueError as exc:
            raise ArchiveError("The archive contains an unsafe path.") from exc
        return destination

    def restore(self, archive_id):
        """Restore one archived subtree to its original location."""
        if not archive_id or os.path.basename(archive_id) != archive_id:
            raise ArchiveError("Invalid archive identifier.")
        archive_path = os.path.join(self.archive_dir, archive_id + ".zip")
        manifest = self._manifest_from_zip(archive_path)
        if manifest["archive_id"] != archive_id:
            raise ArchiveError("The archive identifier does not match its manifest.")

        relative_path, node_path = self._relative_node_path(
            self._local_path(manifest["original_path"])
        )
        note_path = node_path + ".rtf"
        if os.path.exists(node_path) or os.path.exists(note_path):
            raise ArchiveConflictError(
                f'A note already exists at "{relative_path}". Move or rename it before restoring.'
            )

        staging_dir = tempfile.mkdtemp(prefix=".restore-", dir=self.archive_dir)
        try:
            with zipfile.ZipFile(archive_path, "r") as archive:
                for info in archive.infolist():
                    if info.filename == self.MANIFEST_NAME:
                        continue
                    destination = self._safe_member_path(staging_dir, info.filename)
                    if info.is_dir():
                        os.makedirs(destination, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(destination), exist_ok=True)
                    with archive.open(info, "r") as source, open(destination, "wb") as output:
                        shutil.copyfileobj(source, output)

            staged_node = os.path.join(staging_dir, relative_path)
            staged_note = staged_node + ".rtf"
            if not os.path.isdir(staged_node) or not os.path.isfile(staged_note):
                raise ArchiveError("The archive is missing its root note or folder.")

            os.makedirs(os.path.dirname(node_path), exist_ok=True)
            moved = []
            try:
                shutil.move(staged_note, note_path)
                moved.append((note_path, staged_note))
                shutil.move(staged_node, node_path)
                moved.append((node_path, staged_node))
            except Exception:
                for restored_path, staged_path in reversed(moved):
                    if os.path.exists(restored_path) and not os.path.exists(staged_path):
                        shutil.move(restored_path, staged_path)
                raise
            os.remove(archive_path)
        except ArchiveError:
            raise
        except (OSError, ValueError, zipfile.BadZipFile, shutil.Error) as exc:
            raise ArchiveError("Could not restore the compressed archive.") from exc
        finally:
            shutil.rmtree(staging_dir, ignore_errors=True)
        return relative_path
