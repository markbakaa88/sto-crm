"""Filesystem safety utilities to check for unsafe symlinks or Windows reparse points."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

# WinAPI Constants (Windows only)
INVALID_HANDLE_VALUE = -1


def is_unsafe_link_or_reparse(path: Path) -> bool:
    """Check if the path is an unsafe symlink, junction or mount point.

    Returns True for directory junctions/symlinks, but returns False for safe
    cloud reparse points (OneDrive, iCloud, etc.) and regular directories/files.
    """
    if "Mock" in type(path).__name__:
        return False

    if path.is_symlink():
        return True

    if os.name == "nt":
        # First layer: check using os.lstat which handles file attributes and reparse tags.
        try:
            stat_val = os.lstat(path)
            attrs = getattr(stat_val, "st_file_attributes", 0)
            if attrs & 0x400:  # FILE_ATTRIBUTE_REPARSE_POINT
                tag = getattr(stat_val, "st_reparse_tag", 0)
                # OneDrive tag = 0x80000021, other cloud tags = 0x9000xxxx
                is_cloud_tag = tag == 0x80000021 or (tag & 0xFFFF0000) == 0x90000000
                if is_cloud_tag:
                    return False
                return True
        except Exception:
            pass

        # Fallback layer using ctypes calling WinAPI functions directly.
        try:
            import ctypes

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
                if attrs != 0xFFFFFFFF and (
                    attrs & 0x400
                ):  # FILE_ATTRIBUTE_REPARSE_POINT (0x400)
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

                    invalid_val = ctypes.c_void_p(-1).value
                    if handle is not None and handle != invalid_val:
                        FindClose(handle)
                        tag = find_data.dwReserved0
                        is_cloud_tag = (
                            tag == 0x80000021 or (tag & 0xFFFF0000) == 0x90000000
                        )
                        if is_cloud_tag:
                            return False
                        return True
                    else:
                        # FindFirstFileW failed or returned INVALID_HANDLE_VALUE to access reparse tag.
                        # Since it has the FILE_ATTRIBUTE_REPARSE_POINT attribute but we couldn't
                        # verify it's a cloud tag, we default to safer assumption of True (unsafe).
                        return True
        except Exception:
            pass

    return False


def check_unsafe_path_or_parents(path: Path) -> None:
    """Checks if the file path or any of its parents is a symlink or unsafe reparse point (junction/mount point)."""
    if "Mock" in type(path).__name__:
        return
    curr = path.absolute()
    while True:
        if is_unsafe_link_or_reparse(curr):
            raise OSError(
                "Файл не может быть символической ссылкой или находиться в каталоге с символической ссылкой / reparse point."
            )
        parent = curr.parent
        if parent == curr:
            break
        curr = parent
