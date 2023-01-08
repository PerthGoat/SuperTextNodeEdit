# helper functions for SuperText for common tasks
# helps with tests!
import os

def RenamePathToPath(src, dst):
    normalize_src : str = os.path.normpath(src)
    normalize_dst : str = os.path.normpath(dst)
    
    # basic exist checks
    assert os.path.exists(normalize_src)

    dst_parent = os.path.dirname(normalize_dst)
    assert os.path.exists(dst_parent)

    # now check if src path is being renamed to a lower level of itself

    path_elements_src = normalize_src.split(os.path.sep)
    path_elements_dst = normalize_dst.split(os.path.sep)

    while len(path_elements_src) > 0 and len(path_elements_dst) > 0:
        curfold_src = path_elements_src[0]
        curfold_dst = path_elements_dst[0]
        
        if curfold_src == curfold_dst:
            path_elements_src = path_elements_src[1:]
            path_elements_dst = path_elements_dst[1:]

    assert len(path_elements_src) != 0

    return normalize_dst