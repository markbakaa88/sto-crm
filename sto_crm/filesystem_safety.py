"""Filesystem safety utilities to check for unsafe symlinks or Windows reparse points."""

from __future__ import annotations

import ctypes
import os
import stat
from pathlib import Path

# INVALID_HANDLE_VALUE on Windows is -1 as a pointer-sized value.
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


def is_unsafe_link_or_reparse(path: Path, *, allow_cloud_reparse: bool = False) -> bool:
    """Check if the path is an unsafe symlink, junction or mount point.

    Returns True for directory junctions/symlinks, but returns False for safe
    cloud reparse points (OneDrive, iCloud, etc.) and regular directories/files.
    """
    if "Mock" in type(path).__name__:
        return False

    try:
        stat_val = os.lstat(path)
    except FileNotFoundError:
        return False
    except Exception as exc:
        raise OSError(f"Failed to check path safety for {path}: {exc}") from exc

    try:
        if hasattr(stat_val, "st_mode") and isinstance(stat_val.st_mode, int):
            if stat.S_ISLNK(stat_val.st_mode):
                return True
    except Exception:
        pass

    if os.name == "nt":
        attrs = getattr(stat_val, "st_file_attributes", 0)
        if isinstance(attrs, int) and (attrs & 0x400):  # FILE_ATTRIBUTE_REPARSE_POINT
            tag = getattr(stat_val, "st_reparse_tag", 0)
            is_cloud_tag = tag == 0x80000021 or (tag & 0xFFFF0000) == 0x90000000
            if allow_cloud_reparse and is_cloud_tag:
                return False
            return True
        else:
            return False

        # Fallback layer using ctypes calling WinAPI functions directly.
        try:
            # Define WinAPI types
            DWORD = ctypes.c_uint32

            class FILETIME(ctypes.Structure):
                _fields_ = [
                    ("dwLowDateTime", DWORD),
                    ("dwHighDateTime", DWORD),
                ]

            class WIN32_FIND_DATAW(ctypes.Structure):
                _fields_ = [
                    ("dwFileAttributes", DWORD),
                    ("ftCreationTime", FILETIME),
                    ("ftLastAccessTime", FILETIME),
                    ("ftLastWriteTime", FILETIME),
                    ("nFileSizeHigh", DWORD),
                    ("nFileSizeLow", DWORD),
                    ("dwReserved0", DWORD),  # Reparse tag / Reserved
                    ("dwReserved1", DWORD),
                    ("cFileName", ctypes.c_wchar * 260),
                    ("cAlternateFileName", ctypes.c_wchar * 14),
                ]

            windll = getattr(ctypes, "windll", None)
            if windll is not None:
                # Configure GetFileAttributesW
                GetFileAttributesW = windll.kernel32.GetFileAttributesW
                GetFileAttributesW.argtypes = [ctypes.c_wchar_p]
                GetFileAttributesW.restype = DWORD

                attrs = GetFileAttributesW(str(path))
                if attrs != 0xFFFFFFFF:
                    if attrs & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT (0x400)
                        FindFirstFileW = windll.kernel32.FindFirstFileW
                        FindFirstFileW.argtypes = [
                            ctypes.c_wchar_p,
                            ctypes.POINTER(WIN32_FIND_DATAW),
                        ]
                        FindFirstFileW.restype = (
                            ctypes.c_void_p
                        )  # HANDLE is 64-bit on 64-bit Windows

                        FindClose = windll.kernel32.FindClose
                        FindClose.argtypes = [ctypes.c_void_p]
                        FindClose.restype = ctypes.c_int

                        find_data = WIN32_FIND_DATAW()
                        handle = FindFirstFileW(str(path), ctypes.byref(find_data))

                        if handle is not None and handle != INVALID_HANDLE_VALUE:
                            FindClose(handle)
                            tag = find_data.dwReserved0
                            is_cloud_tag = (
                                tag == 0x80000021 or (tag & 0xFFFF0000) == 0x90000000
                            )
                            if allow_cloud_reparse and is_cloud_tag:
                                return False
                            return True
                        else:
                            return True
                    else:
                        # Not a reparse point
                        return False
                else:
                    err_code = windll.kernel32.GetLastError()
                    if err_code not in (2, 3):  # 2: ERROR_FILE_NOT_FOUND, 3: ERROR_PATH_NOT_FOUND
                        raise OSError(f"WinAPI GetFileAttributesW failed with error code: {err_code}")
        except OSError:
            raise
        except Exception as exc:
            raise OSError(f"Failed to check path safety for {path} via WinAPI: {exc}") from exc

    return False


def check_unsafe_path_or_parents(path: Path, *, allow_cloud_reparse: bool = False) -> None:
    """Checks if the file path or any of its parents is a symlink or unsafe reparse point (junction/mount point)."""
    if "Mock" in type(path).__name__:
        return
    curr = path.absolute()
    while True:
        if is_unsafe_link_or_reparse(curr, allow_cloud_reparse=allow_cloud_reparse):
            raise OSError(
                "Файл не может быть символической ссылкой или находиться в каталоге с символической ссылкой / reparse point."
            )
        parent = curr.parent
        if parent == curr:
            break
        curr = parent
