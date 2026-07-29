"""Incremental, disk-backed substring search for SuperText notes."""

from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
import os
import sqlite3
from typing import Iterable

from src.RTFParser import RTFParser


@dataclass(frozen=True)
class SearchResult:
    path: str
    snippet: str


def _first_command(group):
    for token in group:
        if isinstance(token, tuple) and token[0] == "RTFCMD":
            return token[1]
    return None


def _has_direct_command(group, command):
    return any(
        isinstance(token, tuple) and token == ("RTFCMD", command)
        for token in group
    )


def rtf_to_plain_text(rtf_data: str) -> str:
    """Return visible note text while ignoring RTF metadata and embedded data."""
    parsed = RTFParser(rtf_data).parseme()
    output = []

    def visit(group):
        first_command = _first_command(group)
        if first_command in {"fonttbl", "colortbl", "pict"}:
            return
        if _has_direct_command(group, "supertextfile"):
            return
        if _has_direct_command(group, "supertextlink"):
            for child in group:
                if (
                    isinstance(child, list)
                    and _has_direct_command(child, "supertextdisplay")
                ):
                    visit(child)
                    break
            return

        for token in group:
            if isinstance(token, list):
                visit(token)
                continue

            token_type, token_value = token
            if token_type in {"TEXT", "CMDPARAM"}:
                output.append(token_value)
            elif token_type == "RTFCMD":
                if token_value == "par":
                    output.append("\n")
                elif token_value == "tab":
                    output.append("\t")

    visit(parsed)
    return "".join(output)


def _gram_hash(gram: str) -> bytes:
    # Storing hashes avoids keeping a second plaintext copy (or recognizable
    # fragments) of every note inside the cache.
    return hashlib.blake2b(
        gram.encode("utf-8"),
        digest_size=8,
        person=b"STSearch",
    ).digest()


def _ngrams(text: str, width: int) -> set[bytes]:
    normalized = text.casefold()
    return {
        _gram_hash(normalized[index:index + width])
        for index in range(max(0, len(normalized) - width + 1))
    }


def _index_grams(text: str) -> set[bytes]:
    normalized = text.casefold()
    return set().union(
        *(
            _ngrams(normalized, width)
            for width in range(1, min(3, len(normalized)) + 1)
        )
    )


def _query_grams(query: str) -> set[bytes]:
    normalized = query.casefold()
    if not normalized:
        return set()
    return _ngrams(normalized, min(3, len(normalized)))


def _sample_evenly(values: list[bytes], maximum: int) -> list[bytes]:
    if len(values) <= maximum:
        return values
    return [
        values[round(index * (len(values) - 1) / (maximum - 1))]
        for index in range(maximum)
    ]


class NoteSearchIndex:
    """A persistent trigram index whose source of truth remains the RTF files."""

    DB_FILENAME = ".supertext-search.sqlite3"
    ARCHIVE_DIRNAME = ".supertext-archive"
    MAX_QUERY_GRAMS = 64

    def __init__(self, node_root):
        self.node_root = os.path.abspath(os.path.normpath(node_root))
        self.db_path = os.path.join(self.node_root, self.DB_FILENAME)

    def _connect(self):
        os.makedirs(self.node_root, exist_ok=True)
        connection = sqlite3.connect(self.db_path, timeout=30)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                mtime_ns INTEGER NOT NULL,
                size INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS grams (
                path TEXT NOT NULL REFERENCES files(path) ON DELETE CASCADE,
                gram BLOB NOT NULL,
                PRIMARY KEY (path, gram)
            ) WITHOUT ROWID;
            CREATE INDEX IF NOT EXISTS grams_by_gram ON grams(gram, path);
            """
        )
        return connection

    def _iter_note_files(self):
        for directory, _subdirectories, filenames in os.walk(self.node_root):
            if os.path.normcase(directory) == os.path.normcase(self.node_root):
                _subdirectories[:] = [
                    name
                    for name in _subdirectories
                    if name != self.ARCHIVE_DIRNAME
                ]
            for filename in filenames:
                if filename.lower().endswith(".rtf"):
                    full_path = os.path.join(directory, filename)
                    relative_path = os.path.relpath(full_path, self.node_root)
                    yield relative_path, full_path

    @staticmethod
    def _read_rtf(path):
        try:
            with open(path, "r", encoding="utf-8") as source:
                return source.read()
        except UnicodeDecodeError:
            with open(path, "r", errors="replace") as source:
                return source.read()

    def _replace_file(self, connection, relative_path, full_path, stat):
        try:
            plain_text = rtf_to_plain_text(self._read_rtf(full_path))
        except (OSError, ValueError):
            # Malformed/temporarily unreadable notes are recorded so every
            # search does not repeatedly retry them. A file change retries it.
            plain_text = ""

        connection.execute("DELETE FROM files WHERE path = ?", (relative_path,))
        connection.execute(
            "INSERT INTO files(path, mtime_ns, size) VALUES (?, ?, ?)",
            (relative_path, stat.st_mtime_ns, stat.st_size),
        )
        connection.executemany(
            "INSERT INTO grams(path, gram) VALUES (?, ?)",
            ((relative_path, gram) for gram in _index_grams(plain_text)),
        )

    def refresh(self):
        """Incrementally bring the cache in sync with the notebook."""
        with closing(self._connect()) as connection:
            with connection:
                known = {
                    path: (mtime_ns, size)
                    for path, mtime_ns, size in connection.execute(
                        "SELECT path, mtime_ns, size FROM files"
                    )
                }
                present = set()
                updated = 0

                for relative_path, full_path in self._iter_note_files():
                    present.add(relative_path)
                    try:
                        stat = os.stat(full_path)
                    except OSError:
                        continue
                    signature = (stat.st_mtime_ns, stat.st_size)
                    if known.get(relative_path) == signature:
                        continue
                    self._replace_file(
                        connection,
                        relative_path,
                        full_path,
                        stat,
                    )
                    updated += 1

                removed_paths = set(known) - present
                connection.executemany(
                    "DELETE FROM files WHERE path = ?",
                    ((path,) for path in removed_paths),
                )
                return {"updated": updated, "removed": len(removed_paths)}

    def update_file(self, full_path):
        """Update one saved note without walking the whole notebook."""
        full_path = os.path.abspath(os.path.normpath(full_path))
        try:
            if os.path.commonpath([self.node_root, full_path]) != self.node_root:
                return False
            stat = os.stat(full_path)
        except (OSError, ValueError):
            return False

        relative_path = os.path.relpath(full_path, self.node_root)
        with closing(self._connect()) as connection:
            with connection:
                self._replace_file(connection, relative_path, full_path, stat)
        return True

    def _candidate_paths(self, connection, query: str, limit: int):
        grams = sorted(_query_grams(query))
        if not grams:
            return [
                row[0]
                for row in connection.execute(
                    "SELECT path FROM files ORDER BY path"
                )
            ]

        grams = _sample_evenly(grams, self.MAX_QUERY_GRAMS)
        placeholders = ",".join("?" for _ in grams)
        candidate_limit = max(limit * 20, 1000)
        sql = f"""
            SELECT path
            FROM grams
            WHERE gram IN ({placeholders})
            GROUP BY path
            HAVING COUNT(DISTINCT gram) = ?
            ORDER BY path
            LIMIT ?
        """
        parameters: list[object] = [*grams, len(grams), candidate_limit]
        return [row[0] for row in connection.execute(sql, parameters)]

    @staticmethod
    def _snippet(text: str, match_start: int, query_length: int):
        radius = 70
        start = max(0, match_start - radius)
        finish = min(len(text), match_start + query_length + radius)
        snippet = " ".join(text[start:finish].split())
        if start:
            snippet = "\u2026" + snippet
        if finish < len(text):
            snippet += "\u2026"
        return snippet

    def search(self, query: str, limit=200) -> list[SearchResult]:
        """Find case-insensitive substring matches, exactly verified from RTF."""
        if not query or limit <= 0:
            return []

        normalized_query = query.casefold()
        with closing(self._connect()) as connection:
            candidates = self._candidate_paths(connection, query, limit)

        results = []
        for relative_path in candidates:
            full_path = os.path.join(self.node_root, relative_path)
            try:
                text = rtf_to_plain_text(self._read_rtf(full_path))
            except (OSError, ValueError):
                continue
            match_start = text.casefold().find(normalized_query)
            if match_start < 0:
                continue
            results.append(
                SearchResult(
                    path=os.path.splitext(relative_path)[0],
                    snippet=self._snippet(text, match_start, len(query)),
                )
            )
            if len(results) >= limit:
                break
        return results

    def refresh_and_search(self, query: str, limit=200):
        refresh_stats = self.refresh()
        return refresh_stats, self.search(query, limit=limit)
