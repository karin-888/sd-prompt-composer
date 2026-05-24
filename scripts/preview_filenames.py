# -*- coding: UTF-8 -*-
"""Filesystem-safe preview filenames for tag dictionary images."""

from __future__ import annotations

import os
import shutil
from typing import Dict, Iterable, Optional, Set, Tuple

_PREVIEW_EXTS = (".webp", ".png", ".jpg", ".jpeg", ".gif")

# Fullwidth substitutes keep filenames human-readable and reversible.
_TO_SAFE = str.maketrans(
    {
        "/": "／",
        "\\": "＼",
        ":": "：",
        "\n": " ",
        "\r": "",
    }
)
_FROM_SAFE = str.maketrans(
    {
        "／": "/",
        "＼": "\\",
        "：": ":",
    }
)


def tag_to_preview_basename(tag: str) -> str:
    return (tag or "").strip().translate(_TO_SAFE)


def preview_basename_to_tag(basename: str) -> str:
    return (basename or "").strip().translate(_FROM_SAFE)


def tag_from_preview_filename(filename: str) -> str:
    """Recover tag string from a preview filename (handles tags ending with '.')."""
    name = os.path.basename(filename or "")
    lower = name.lower()
    for ext in _PREVIEW_EXTS:
        if lower.endswith(ext):
            return preview_basename_to_tag(name[: -len(ext)])
    return preview_basename_to_tag(name)


def preview_path_for_tag(previews_dir: str, tag: str, ext: str = ".webp") -> str:
    ext = ext if ext.startswith(".") else f".{ext}"
    if ext.lower() not in _PREVIEW_EXTS:
        ext = ".webp"
    return os.path.join(previews_dir, tag_to_preview_basename(tag) + ext)


def _is_preview_file(path: str) -> bool:
    lower = os.path.basename(path).lower()
    return any(lower.endswith(ext) for ext in _PREVIEW_EXTS)


def _iter_preview_files(previews_dir: str) -> Iterable[str]:
    if not previews_dir or not os.path.isdir(previews_dir):
        return
    for root, _dirs, files in os.walk(previews_dir):
        for fname in files:
            if fname in (".", ".."):
                continue
            path = os.path.join(root, fname)
            if _is_preview_file(path):
                yield path


def reconstruct_tag_from_legacy_path(previews_dir: str, filepath: str) -> str:
    rel = os.path.relpath(filepath, previews_dir)
    parts = rel.split(os.sep)
    stem = os.path.splitext(parts[-1])[0]

    if len(parts) == 1:
        return preview_basename_to_tag(stem)

    parent = parts[0]
    if parent.endswith(" "):
        return f"{parent.rstrip()} / {stem.strip()}"

    # Tag ending with "\X/" was split into "...prefix, \X/.webp"
    if stem == "" or parts[-1].startswith("."):
        if parent.endswith("\\o"):
            return f"{parent}/"
        if parent == "\\o":
            return "\\o/"
        return parent

    return preview_basename_to_tag(stem)


def _choose_tag(candidates: Set[str], known_tags: Optional[Set[str]]) -> Optional[str]:
    if not candidates:
        return None
    if known_tags:
        matched = [t for t in candidates if t in known_tags]
        if len(matched) == 1:
            return matched[0]
        if matched:
            return sorted(matched, key=len)[0]
    if len(candidates) == 1:
        return next(iter(candidates))
    return sorted(candidates, key=len)[0]


def _legacy_relative_path(tag: str, ext: str = ".webp") -> str:
    """Relative path produced by the old unsanitized naming scheme."""
    return tag + ext


def _match_tag_from_known(filepath: str, previews_dir: str, known_tags: Set[str]) -> Optional[str]:
    rel = os.path.relpath(filepath, previews_dir)
    rel_norm = rel.replace(os.sep, "/")
    for tag in known_tags:
        for ext in _PREVIEW_EXTS:
            legacy = _legacy_relative_path(tag, ext)
            if legacy.replace(os.sep, "/") == rel_norm:
                return tag
    return None


def resolve_tag_for_preview_file(
    previews_dir: str,
    filepath: str,
    known_tags: Optional[Set[str]] = None,
) -> str:
    if known_tags:
        matched = _match_tag_from_known(filepath, previews_dir, known_tags)
        if matched:
            return matched

    rel = os.path.relpath(filepath, previews_dir)
    candidates: Set[str] = set()

    if os.sep not in rel and "/" not in rel:
        candidates.add(tag_from_preview_filename(os.path.basename(rel)))
    else:
        candidates.add(reconstruct_tag_from_legacy_path(previews_dir, filepath))
        candidates.add(tag_from_preview_filename(os.path.basename(rel)))

    chosen = _choose_tag(candidates, known_tags)
    return chosen or reconstruct_tag_from_legacy_path(previews_dir, filepath)


def migrate_preview_files(
    previews_dir: str,
    *,
    known_tags: Optional[Set[str]] = None,
    dry_run: bool = False,
) -> Dict[str, int]:
    """Flatten/rename legacy preview files to sanitized top-level names."""
    stats = {"scanned": 0, "migrated": 0, "skipped": 0, "removed_dirs": 0, "errors": 0}

    if not previews_dir or not os.path.isdir(previews_dir):
        return stats

    planned: Dict[str, Tuple[str, str]] = {}
    for src in _iter_preview_files(previews_dir):
        stats["scanned"] += 1
        tag = resolve_tag_for_preview_file(previews_dir, src, known_tags)
        ext = os.path.splitext(src)[1].lower()
        dest = preview_path_for_tag(previews_dir, tag, ext)

        prev = planned.get(dest)
        if prev and prev[0] != src:
            if os.path.getsize(src) <= os.path.getsize(prev[0]):
                stats["skipped"] += 1
                continue
        planned[dest] = (src, tag)

    for dest, (src, _tag) in planned.items():
        if os.path.normpath(src) == os.path.normpath(dest):
            stats["skipped"] += 1
            continue
        try:
            if not dry_run:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                if os.path.isfile(dest):
                    os.remove(dest)
                shutil.move(src, dest)
            stats["migrated"] += 1
        except OSError:
            stats["errors"] += 1

    if not dry_run:
        for root, dirs, _files in os.walk(previews_dir, topdown=False):
            if root == previews_dir:
                continue
            try:
                if not os.listdir(root):
                    os.rmdir(root)
                    stats["removed_dirs"] += 1
            except OSError:
                stats["errors"] += 1

    return stats


def scan_previews(previews_dir: str) -> Dict[str, str]:
    """Return {tag: absolute_path} for all preview images under previews_dir."""
    found: Dict[str, str] = {}
    if not previews_dir or not os.path.isdir(previews_dir):
        return found

    for path in _iter_preview_files(previews_dir):
        rel = os.path.relpath(path, previews_dir)
        if os.sep in rel or "/" in rel:
            tag = reconstruct_tag_from_legacy_path(previews_dir, path)
        else:
            tag = tag_from_preview_filename(os.path.basename(rel))
        if tag and tag not in found:
            found[tag] = path
    return found
