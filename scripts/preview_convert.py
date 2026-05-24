# -*- coding: UTF-8 -*-
"""Convert tag preview images to WebP for smaller storage."""

from __future__ import annotations

import io
import os
from typing import Dict, Optional

from PIL import Image

import preview_filenames

_DEFAULT_QUALITY = 82
_NON_WEBP_EXTS = (".png", ".jpg", ".jpeg", ".gif")


def webp_dest_path(path: str) -> str:
    return os.path.splitext(path)[0] + ".webp"


def _prepare_image(im: Image.Image) -> Image.Image:
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        return im.convert("RGBA")
    return im.convert("RGB")


def save_image_as_webp(
    src_path: str,
    dest_path: str,
    *,
    quality: int = _DEFAULT_QUALITY,
    delete_src: bool = False,
) -> bool:
    dest_path = webp_dest_path(dest_path)
    try:
        with Image.open(src_path) as im:
            prepared = _prepare_image(im)
            os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
            prepared.save(dest_path, "WEBP", quality=quality, method=4)
        if delete_src and os.path.normpath(src_path) != os.path.normpath(dest_path):
            try:
                os.remove(src_path)
            except OSError:
                pass
        return True
    except OSError:
        return False


def save_bytes_as_webp(
    data: bytes,
    dest_path: str,
    *,
    quality: int = _DEFAULT_QUALITY,
) -> bool:
    dest_path = webp_dest_path(dest_path)
    if len(data) < 128:
        return False
    try:
        with Image.open(io.BytesIO(data)) as im:
            prepared = _prepare_image(im)
            os.makedirs(os.path.dirname(dest_path) or ".", exist_ok=True)
            prepared.save(dest_path, "WEBP", quality=quality, method=4)
        return True
    except OSError:
        return False


def convert_previews_dir_to_webp(
    previews_dir: str,
    *,
    quality: int = _DEFAULT_QUALITY,
    dry_run: bool = False,
    delete_original: bool = True,
) -> Dict[str, int]:
    stats = {
        "scanned": 0,
        "converted": 0,
        "skipped_webp": 0,
        "skipped_exists": 0,
        "errors": 0,
        "bytes_before": 0,
        "bytes_after": 0,
    }

    if not previews_dir or not os.path.isdir(previews_dir):
        return stats

    for path in preview_filenames._iter_preview_files(previews_dir):
        stats["scanned"] += 1
        ext = os.path.splitext(path)[1].lower()
        if ext == ".webp":
            stats["skipped_webp"] += 1
            continue

        dest = webp_dest_path(path)
        src_size = os.path.getsize(path)
        stats["bytes_before"] += src_size

        if os.path.isfile(dest) and os.path.getsize(dest) > 0:
            stats["skipped_exists"] += 1
            if delete_original and not dry_run:
                try:
                    os.remove(path)
                except OSError:
                    stats["errors"] += 1
            continue

        if dry_run:
            stats["converted"] += 1
            continue

        if save_image_as_webp(path, dest, quality=quality, delete_src=False):
            dest_size = os.path.getsize(dest) if os.path.isfile(dest) else 0
            stats["bytes_after"] += dest_size
            stats["converted"] += 1
            if delete_original:
                try:
                    os.remove(path)
                except OSError:
                    stats["errors"] += 1
        else:
            stats["errors"] += 1

    return stats
