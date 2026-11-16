"""Helpers for generating native icons from project PNG files."""

from io import BytesIO
from pathlib import Path
import struct

import pygame


_ICON_SIZES = (16, 32, 48, 64, 128, 256)
_ICNS_SIZES = (
    (16, b"icp4"),
    (32, b"icp5"),
    (64, b"icp6"),
    (128, b"ic07"),
    (256, b"ic08"),
    (512, b"ic09"),
    (1024, b"ic10"),
)
_ANDROID_ICON_SIZES = (
    ("mdpi", 48),
    ("hdpi", 72),
    ("xhdpi", 96),
    ("xxhdpi", 144),
    ("xxxhdpi", 192),
)


def _png_images(image_path: Path, sizes: tuple[int, ...]) -> list[tuple[int, bytes]]:
    try:
        image = pygame.image.load(str(image_path))
    except pygame.error as error:
        raise ValueError(f"Could not load project icon image {image_path}: {error}") from error
    if image.get_width() < 1 or image.get_height() < 1:
        raise ValueError(f"Project icon image has invalid dimensions: {image_path}")

    images = []
    for size in sizes:
        scaled = pygame.transform.smoothscale(image, (size, size))
        png = BytesIO()
        pygame.image.save(scaled, png, "icon.png")
        images.append((size, png.getvalue()))
    return images


def make_ico(image_path: Path) -> bytes:
    images = _png_images(Path(image_path), _ICON_SIZES)
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = []
    payloads = []
    offset = 6 + 16 * len(images)
    for size, data in images:
        entries.append(
            struct.pack(
                "<BBBBHHII",
                0 if size == 256 else size,
                0 if size == 256 else size,
                0,
                0,
                1,
                32,
                len(data),
                offset,
            )
        )
        payloads.append(data)
        offset += len(data)
    return header + b"".join(entries) + b"".join(payloads)


def make_icns(image_path: Path) -> bytes:
    images = _png_images(Path(image_path), tuple(size for size, _ in _ICNS_SIZES))
    chunks = []
    for (size, code), (image_size, data) in zip(_ICNS_SIZES, images):
        if size != image_size:
            raise RuntimeError("The generated macOS icon sizes do not match.")
        chunks.append(code + struct.pack(">I", len(data) + 8) + data)
    content = b"".join(chunks)
    return b"icns" + struct.pack(">I", len(content) + 8) + content


def install_android_launcher_icons(image_path: Path, resources_directory: Path) -> None:
    try:
        image = pygame.image.load(str(image_path))
    except pygame.error as error:
        raise ValueError(f"Could not load Android app icon image {image_path}: {error}") from error
    if image.get_width() < 1 or image.get_height() < 1:
        raise ValueError(f"Android app icon image has invalid dimensions: {image_path}")

    try:
        for density, icon_size in _ANDROID_ICON_SIZES:
            directory = Path(resources_directory) / f"mipmap-{density}"
            directory.mkdir(parents=True, exist_ok=True)
            square_icon = pygame.transform.smoothscale(image, (icon_size, icon_size))
            for name in ("ic_launcher.png", "ic_launcher_round.png"):
                pygame.image.save(square_icon, str(directory / name))

            foreground_size = icon_size * 2
            foreground = pygame.Surface((foreground_size, foreground_size), pygame.SRCALPHA, 32)
            artwork_size = foreground_size * 2 // 3
            artwork = pygame.transform.smoothscale(image, (artwork_size, artwork_size))
            foreground.blit(
                artwork,
                ((foreground_size - artwork_size) // 2, (foreground_size - artwork_size) // 2),
            )
            pygame.image.save(foreground, str(directory / "ic_launcher_foreground.png"))
    except pygame.error as error:
        raise ValueError(f"Could not generate Android app icons from {image_path}: {error}") from error


def update_windows_executable_icon(executable: Path, ico_data: bytes) -> None:
    import ctypes
    from ctypes import wintypes

    if not hasattr(ctypes, "WinDLL"):
        raise RuntimeError("Custom Windows executable icons can only be applied on Windows.")

    reserved, icon_type, count = struct.unpack_from("<HHH", ico_data)
    if reserved != 0 or icon_type != 1 or count == 0:
        raise ValueError("The generated Windows icon is invalid.")

    entries = []
    for index in range(count):
        entry_offset = 6 + index * 16
        width, height, colors, entry_reserved, planes, bits, size, offset = struct.unpack_from(
            "<BBBBHHII", ico_data, entry_offset
        )
        if entry_reserved != 0:
            raise ValueError("The generated Windows icon contains an invalid entry.")
        entries.append((width, height, colors, planes, bits, ico_data[offset : offset + size]))

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.BeginUpdateResourceW.argtypes = [wintypes.LPCWSTR, wintypes.BOOL]
    kernel32.BeginUpdateResourceW.restype = wintypes.HANDLE
    kernel32.UpdateResourceW.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.WORD,
        wintypes.LPVOID,
        wintypes.DWORD,
    ]
    kernel32.UpdateResourceW.restype = wintypes.BOOL
    kernel32.EndUpdateResourceW.argtypes = [wintypes.HANDLE, wintypes.BOOL]
    kernel32.EndUpdateResourceW.restype = wintypes.BOOL

    def resource_id(value: int):
        return ctypes.cast(ctypes.c_void_p(value), wintypes.LPCWSTR)

    handle = kernel32.BeginUpdateResourceW(str(executable), False)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        group_entries = []
        for index, (width, height, colors, planes, bits, data) in enumerate(entries, start=1):
            image_buffer = ctypes.create_string_buffer(data)
            if not kernel32.UpdateResourceW(
                handle,
                resource_id(3),
                resource_id(index),
                0,
                image_buffer,
                len(data),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            group_entries.append(
                struct.pack("<BBBBHHIH", width, height, colors, 0, planes, bits, len(data), index)
            )

        group_data = struct.pack("<HHH", 0, 1, len(entries)) + b"".join(group_entries)
        group_buffer = ctypes.create_string_buffer(group_data)
        if not kernel32.UpdateResourceW(
            handle,
            resource_id(14),
            resource_id(1),
            0,
            group_buffer,
            len(group_data),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if not kernel32.EndUpdateResourceW(handle, False):
            handle = None
            raise ctypes.WinError(ctypes.get_last_error())
        handle = None
    finally:
        if handle:
            kernel32.EndUpdateResourceW(handle, True)
