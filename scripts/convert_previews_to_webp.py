#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Convert non-WebP tag preview images to WebP."""

from __future__ import annotations

import argparse
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import preview_convert
import user_storage


def _format_bytes(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert tag preview images to WebP.")
    parser.add_argument(
        "previews_dir",
        nargs="?",
        help="Preview directory (default: WebUI data_path or extension data/tag-previews)",
    )
    parser.add_argument("--quality", type=int, default=82, help="WebP quality (default: 82)")
    parser.add_argument("--dry-run", action="store_true", help="Report only, do not convert")
    parser.add_argument(
        "--keep-original",
        action="store_true",
        help="Keep source JPG/PNG files after conversion",
    )
    args = parser.parse_args()

    if args.previews_dir:
        previews_dir = os.path.abspath(args.previews_dir)
    else:
        ext_dir = os.path.dirname(_SCRIPT_DIR)
        previews_dir = user_storage.tag_previews_dir(ext_dir)

    print(f"[convert] dir: {previews_dir}")
    stats = preview_convert.convert_previews_dir_to_webp(
        previews_dir,
        quality=args.quality,
        dry_run=args.dry_run,
        delete_original=not args.keep_original,
    )

    saved = stats["bytes_before"] - stats["bytes_after"]
    print(
        f"[convert] scanned={stats['scanned']} converted={stats['converted']} "
        f"already_webp={stats['skipped_webp']} webp_exists={stats['skipped_exists']} "
        f"errors={stats['errors']}"
    )
    if stats["bytes_before"]:
        print(
            f"[convert] size: {_format_bytes(stats['bytes_before'])} -> "
            f"{_format_bytes(stats['bytes_after'])} "
            f"(saved {_format_bytes(max(0, saved))})"
        )
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
