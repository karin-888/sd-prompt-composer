#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Import local wildcard .txt / package .yaml files into group_tags YAML.

Reads wildcard packs under ``~/Downloads/Wildcard`` (or ``--root``), skips bulk
artist/character dump files, and writes one or more YAML files under
``group_tags/wildcards*.yaml``.

Also prints the path to register in ``wildcards.py`` for ``__token__`` insertion.
"""

from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from typing import Dict, List, Optional, Set, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
for _p in (_SCRIPT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tag_text_utils as ttu

DEFAULT_ROOT = os.path.expanduser(
    "/Users/hiori222/Downloads/Wildcard"
)
SECTION_NAME = "Wildcards"

# Files that are megascale artist/character dumps — not useful in tag dictionary.
SKIP_FILE_PATTERNS = (
    r"danbooruArtistsAll",
    r"danbooruCharsAll",
    r"danbooru_artist",
    r"danbooru_character",
    r"e621ArtistsAll",
    r"e621CharsAll",
    r"e621_artist",
    r"e621_character",
    r"\.zip\.txt$",
)
SKIP_FILE_RE = [re.compile(p, re.I) for p in SKIP_FILE_PATTERNS]

MAX_FILE_LINES = 500
MAX_LINE_LEN = 120

# Categories that get their own YAML (rest merged into wildcards.yaml).
SPLIT_CATEGORIES = {
    "_Illustrious": "wildcards_illustrious.yaml",
    "civitai-wildcard-prompt-main": "wildcards_civitai_prompt.yaml",
}

PACKAGE_YAML_FILES = (
    "NSFW-ALLIN-package.yaml",
    "gentlman-ALL-IN-package.yaml",
)


def _norm_key(line: str) -> str:
    parts = [p.strip().strip("_") for p in line.split(",")]
    return ", ".join(p.replace(" ", "_") for p in parts if p)


def _should_skip_file(path: str) -> bool:
    base = os.path.basename(path)
    rel = path.replace("\\", "/")
    return any(p.search(base) or p.search(rel) for p in SKIP_FILE_RE)


def _jp_from_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        return ""
    m = re.match(r"^(.+?)[\-_－—]([ぁ-んァ-ン一-龥\u3000-\u303f].*)$", name)
    if m:
        jp = ttu.clean_catalog_jp_label(m.group(2).strip("：: "))
        if jp:
            return jp
    m = re.search(r"[（(]([ぁ-んァ-ン一-龥][^）)]*)[）)]", name)
    if m:
        return m.group(1).strip()
    if ttu.looks_like_japanese(name):
        return name
    return ""


def _group_label(rel_path: str) -> str:
    stem = os.path.splitext(rel_path.replace("\\", "/"))[0]
    leaf = stem.split("/")[-1]
    jp = _jp_from_name(leaf)
    if jp:
        return f"{leaf} ({jp})" if jp != leaf else leaf
    return stem


def _line_jp(line: str, group_jp: str, group_name: str) -> str:
    if group_jp:
        return group_jp
    # Single-clause short tags: reuse group hint or tag itself.
    if "," not in line and len(line) <= 40:
        return line.replace("_", " ")
    clean = _group_label(group_name)
    return clean or line[:40]


def _usable_line(line: str) -> Optional[str]:
    line = (line or "").strip()
    if not line or line.startswith("#"):
        return None
    if "__" in line:
        return None
    if len(line) > MAX_LINE_LEN:
        return None
    if not re.search(r"[a-zA-Z]", line):
        return None
    # Allow multi-clause prompts but reject obvious scene dumps.
    if re.search(r"\b1girl\b|\b1boy\b|\bsweat,pov\b", line, re.I):
        return None
    return _norm_key(line)


def _load_existing_tags(group_tags_dir: str) -> Set[str]:
    existing: Set[str] = set()
    for yf in glob.glob(os.path.join(group_tags_dir, "*.yaml")):
        if os.path.basename(yf).startswith("wildcards"):
            continue
        try:
            with open(yf, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or []
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for sec in data:
            for cat in sec.get("categories", []):
                for grp in cat.get("groups", []):
                    for k in grp.get("tags") or {}:
                        existing.add(k)
    return existing


def _parse_txt_file(
    fp: str,
    rel: str,
    existing: Set[str],
    global_seen: Set[str],
) -> Dict[str, str]:
    lines: List[str] = []
    try:
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            for raw in f:
                k = _usable_line(raw)
                if k:
                    lines.append(k)
    except OSError:
        return {}

    if not lines or len(lines) > MAX_FILE_LINES:
        return {}

    group_name = os.path.splitext(rel.replace("\\", "/"))[0]
    group_jp = _jp_from_name(os.path.basename(group_name))
    out: Dict[str, str] = {}
    for key in lines:
        if key in existing or key in global_seen:
            continue
        global_seen.add(key)
        out[key] = _line_jp(key, group_jp, group_name)
    return out


def _parse_yaml_package(
    data,
    existing: Set[str],
    global_seen: Set[str],
) -> Dict[str, Dict[str, str]]:
    """Parse a wildcard package YAML into {group_name: {tag: jp}}."""
    groups: Dict[str, Dict[str, str]] = {}

    def walk(obj, group_path: List[str]) -> None:
        if isinstance(obj, list):
            gname = group_path[-1] if group_path else "default"
            jp_hint = _jp_from_name(gname)
            bucket = groups.setdefault(gname, {})
            for item in obj:
                if not isinstance(item, str):
                    continue
                k = _usable_line(item)
                if not k or k in existing or k in global_seen:
                    continue
                global_seen.add(k)
                bucket[k] = jp_hint or _line_jp(k, jp_hint, gname)
            return
        if isinstance(obj, dict):
            for key, val in obj.items():
                walk(val, group_path + [str(key).strip()])

    walk(data, [])
    return groups


def _collect_from_root(root: str, existing: Set[str]) -> Dict[str, Dict[str, Dict[str, str]]]:
    """Return {category: {group: {tag: jp}}}."""
    per_cat: Dict[str, Dict[str, Dict[str, str]]] = {}
    global_seen: Set[str] = set()

    for name in sorted(os.listdir(root)):
        top = os.path.join(root, name)
        if not os.path.isdir(top):
            continue
        cat = name
        cat_groups = per_cat.setdefault(cat, {})
        for dirpath, _, filenames in os.walk(top):
            for fn in filenames:
                if not fn.lower().endswith(".txt"):
                    continue
                fp = os.path.join(dirpath, fn)
                if _should_skip_file(fp):
                    continue
                rel = os.path.relpath(fp, top).replace("\\", "/")
                tags = _parse_txt_file(fp, rel, existing, global_seen)
                if not tags:
                    continue
                grp = _group_label(rel)
                bucket = cat_groups.setdefault(grp, {})
                for k, v in tags.items():
                    bucket.setdefault(k, v)

    for pkg in PACKAGE_YAML_FILES:
        fp = os.path.join(root, pkg)
        if not os.path.isfile(fp):
            continue
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            print(f"[wildcards] skip package {pkg}: {e}")
            continue
        if not data:
            continue
        cat = os.path.splitext(pkg)[0]
        cat_groups = per_cat.setdefault(cat, {})
        pkg_groups = _parse_yaml_package(data, existing, global_seen)
        for gname, tags in pkg_groups.items():
            if not tags:
                continue
            jp = _jp_from_name(gname)
            grp = f"{gname} ({jp})" if jp and jp != gname else gname
            bucket = cat_groups.setdefault(grp, {})
            for k, v in tags.items():
                bucket.setdefault(k, v)
    return per_cat


def _build_section(categories: Dict[str, Dict[str, Dict[str, str]]]) -> List[Dict]:
    section = {"name": SECTION_NAME, "categories": []}
    for cat_name in sorted(categories.keys()):
        groups = categories[cat_name]
        if not groups:
            continue
        cat_obj = {"name": cat_name, "groups": []}
        for gname in sorted(groups.keys()):
            tags = groups[gname]
            if not tags:
                continue
            cat_obj["groups"].append(
                {
                    "name": gname,
                    "tags": dict(sorted(tags.items(), key=lambda kv: kv[0].lower())),
                }
            )
        if cat_obj["groups"]:
            section["categories"].append(cat_obj)
    return [section]


def _write_outputs(
    per_cat: Dict[str, Dict[str, Dict[str, str]]],
    out_dir: str,
    dry_run: bool,
) -> List[Tuple[str, int]]:
    # Split large categories into dedicated files.
    buckets: Dict[str, Dict[str, Dict[str, Dict[str, str]]]] = {
        "wildcards.yaml": {},
        "wildcards_illustrious.yaml": {},
        "wildcards_civitai_prompt.yaml": {},
    }
    for cat, groups in per_cat.items():
        target = SPLIT_CATEGORIES.get(cat, "wildcards.yaml")
        if target not in buckets:
            buckets[target] = {}
        buckets[target][cat] = groups

    written: List[Tuple[str, int]] = []
    for fname, cats in buckets.items():
        if not cats:
            continue
        n = sum(len(t) for g in cats.values() for t in g.values())
        path = os.path.join(out_dir, fname)
        print(f"[wildcards] {fname}: categories={len(cats)} tags={n}")
        if dry_run:
            written.append((fname, n))
            continue
        data = _build_section(cats)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                data,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=200,
            )
        written.append((fname, n))
    return written


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=DEFAULT_ROOT)
    parser.add_argument(
        "--out-dir",
        default=os.path.join(_SCRIPT_DIR, "..", "group_tags"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = os.path.abspath(os.path.expanduser(args.root))
    out_dir = os.path.abspath(args.out_dir)
    if not os.path.isdir(root):
        print(f"[wildcards] root not found: {root}")
        raise SystemExit(1)

    existing = _load_existing_tags(out_dir)
    print(f"[wildcards] existing dictionary tags (excl. wildcards*.yaml): {len(existing)}")

    per_cat = _collect_from_root(root, existing)
    grand = sum(len(t) for g in per_cat.values() for t in g.values())
    print(f"[wildcards] categories={len(per_cat)} new_tags={grand}")

    written = _write_outputs(per_cat, out_dir, args.dry_run)

    if not args.dry_run:
        import normalize_tag_spaces as nt

        for fname, _ in written:
            path = os.path.join(out_dir, fname)
            if os.path.isfile(path):
                n = nt.process_file(path)
                print(f"[wildcards] normalized {fname}: {n} keys")


if __name__ == "__main__":
    main()
