#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Build a curated wildcard *tag collection* YAML for the tag dictionary UI.

Keeps the raw ``wildcards*.yaml`` files untouched and writes separate
``wildcards_tag_collection*.yaml`` files with:

- thematic categories (ポーズ, 髪型, 服装, …)
- readable group names (pack / file stem + optional Japanese hint)
- Japanese labels resolved via danbooru translations + existing dictionaries

Raw wildcard archives (``wildcards.yaml`` etc.) remain for full prompt lines.
"""

from __future__ import annotations

import argparse
import csv
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
from import_wildcards import (
    DEFAULT_ROOT,
    PACKAGE_YAML_FILES,
    SKIP_FILE_RE,
    _jp_from_name,
    _norm_key,
    _should_skip_file,
)

SECTION_NAME = "ワイルドカード タグ集"
MAX_FILE_LINES = 500
MAX_TAG_LEN = 80
MAX_COMMAS = 3

SPLIT_PACKS = {
    "_Illustrious": "wildcards_tag_collection_illustrious.yaml",
    "civitai-wildcard-prompt-main": "wildcards_tag_collection_civitai.yaml",
}

THEME_RULES: Tuple[Tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"pose|posing|gesture|stand|sitting|lying|walk|run|dance|action", re.I), "ポーズ・動作"),
    (re.compile(r"hair|bangs|ponytail|braid|twintail|ahoge", re.I), "髪型・髪色"),
    (re.compile(r"express|emotion|face|smile|ahegao|blush|cry", re.I), "表情・雰囲気"),
    (re.compile(r"cloth|outfit|dress|uniform|lingerie|swimsuit|fashion|wear|bra|pant", re.I), "服装・ファッション"),
    (re.compile(r"background|scenery|location|environment|room|outdoor", re.I), "背景・環境"),
    (re.compile(r"light|camera|angle|composition|quality|masterpiece|style|hdr", re.I), "画質・構図・カメラ"),
    (re.compile(r"sex|nsfw|breast|pussy|penis|cum|bondage|fellatio|handjob|ahegao", re.I), "NSFW"),
    (re.compile(r"color|palette|theme", re.I), "色・テーマ"),
)

PACK_LABELS = {
    "_Illustrious": "Illustrious",
    "_Pony": "Pony",
    "_NoobAI": "NoobAI",
    "_SDXL_1.0": "SDXL",
    "_SD_1.5": "SD1.5",
    "_Flux.1_D": "Flux.1",
    "_Other": "Other",
    "wildcards": "汎用ワイルドカード",
    "civitai-wildcard-prompt-main": "Civitai Prompt",
    "200WildcardsNSFWAnd_sdWildcards_Wildcards": "200+ Wildcards",
    "thePromptBuilder_v15": "Prompt Builder",
    "NSFW-ALLIN-package": "NSFW ALL-IN",
}


def _load_jp_lookup(group_tags_dir: str) -> Dict[str, str]:
    items: List[Dict[str, str]] = []
    for yf in glob.glob(os.path.join(group_tags_dir, "*.yaml")):
        base = os.path.basename(yf)
        if base.startswith("wildcards"):
            continue
        try:
            with open(yf, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or []
        except OSError:
            continue
        if not isinstance(data, list):
            continue
        for sec in data:
            for cat in sec.get("categories", []) or []:
                for grp in cat.get("groups", []) or []:
                    for key, value in (grp.get("tags") or {}).items():
                        jp = value
                        if isinstance(value, dict):
                            jp = value.get("jp") or value.get("label") or ""
                        items.append({"tag": str(key), "jp": str(jp)})

    lookup = ttu.build_jp_lookup(items)

    trans_csv = os.path.join(os.path.dirname(group_tags_dir), "tags", "danbooru_translations_jp.csv")
    if os.path.isfile(trans_csv):
        with open(trans_csv, encoding="utf-8") as f:
            for row in csv.reader(f):
                if len(row) < 2:
                    continue
                tag, jp_raw = row[0].strip(), row[1].strip()
                if not tag or not jp_raw:
                    continue
                jp = jp_raw.split(",")[0].strip()
                key = ttu.normalize_lookup_key(tag)
                if key and jp and key not in lookup:
                    lookup[key] = jp
    return lookup


def _tag_collection_line(raw: str) -> Optional[str]:
    line = (raw or "").strip()
    if not line or line.startswith("#"):
        return None
    if "__" in line or len(line) > MAX_TAG_LEN or line.count(",") > MAX_COMMAS:
        return None
    if "<lora:" in line.lower() or "{" in line or "|" in line:
        return None
    if not re.search(r"[a-zA-Z]", line):
        return None
    if re.search(r"\b1girl\b|\b1boy\b|\bsweat,pov\b", line, re.I):
        return None
    return _norm_key(line)


def _theme_for(rel_path: str, pack_name: str) -> str:
    rel_l = rel_path.lower()
    pack_l = pack_name.lower()
    for rx, label in THEME_RULES:
        # Do not classify an entire pack as NSFW just because its folder name contains "nsfw".
        if label == "NSFW":
            if rx.search(rel_l):
                return label
            continue
        if rx.search(rel_l) or rx.search(pack_l):
            return label
    return "その他"


def _pack_label(name: str) -> str:
    return PACK_LABELS.get(name, name)


def _resolve_jp(tag: str, group_jp: str, lookup: Dict[str, str]) -> str:
    jp = ttu.resolve_jp_label(tag, group_jp, lookup)
    if jp:
        return jp
    clause = ttu.tag_first_clause(tag)
    jp = ttu.resolve_jp_label(clause, "", lookup)
    if jp:
        return jp
    if group_jp:
        return group_jp
    if "," not in tag and len(tag) <= 48:
        return clause.replace("_", " ")
    return clause.replace("_", " ")


def _group_display(pack: str, rel_path: str) -> str:
    stem = os.path.splitext(rel_path.replace("\\", "/"))[0]
    leaf = stem.split("/")[-1]
    jp = _jp_from_name(leaf)
    pack_short = _pack_label(pack)
    if jp and jp != leaf:
        return f"{pack_short} / {leaf}（{jp}）"
    return f"{pack_short} / {leaf}"


def _collect_txt(
    root: str,
    existing: Set[str],
    global_seen: Set[str],
    lookup: Dict[str, str],
) -> Dict[str, Dict[str, Dict[str, str]]]:
    """Return {pack_name: {theme: {group: {tag: jp}}}}."""
    per_pack: Dict[str, Dict[str, Dict[str, Dict[str, str]]]] = {}

    for pack_name in sorted(os.listdir(root)):
        top = os.path.join(root, pack_name)
        if not os.path.isdir(top):
            continue
        for dirpath, _, filenames in os.walk(top):
            for fn in filenames:
                if not fn.lower().endswith(".txt"):
                    continue
                fp = os.path.join(dirpath, fn)
                if _should_skip_file(fp):
                    continue
                rel = os.path.relpath(fp, top).replace("\\", "/")
                lines: List[str] = []
                try:
                    with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                        for raw in f:
                            k = _tag_collection_line(raw)
                            if k:
                                lines.append(k)
                except OSError:
                    continue
                if not lines or len(lines) > MAX_FILE_LINES:
                    continue

                theme = _theme_for(rel, pack_name)
                group = _group_display(pack_name, rel)
                group_jp = _jp_from_name(os.path.splitext(os.path.basename(rel))[0])
                bucket = per_pack.setdefault(pack_name, {}).setdefault(theme, {}).setdefault(group, {})

                for key in lines:
                    if key in existing or key in global_seen:
                        continue
                    global_seen.add(key)
                    bucket[key] = _resolve_jp(key, group_jp, lookup)
    return per_pack


def _parse_yaml_package_tc(
    data,
    existing: Set[str],
    global_seen: Set[str],
) -> Dict[str, Dict[str, str]]:
    groups: Dict[str, Dict[str, str]] = {}

    def walk(obj, group_path: List[str]) -> None:
        if isinstance(obj, list):
            gname = group_path[-1] if group_path else "default"
            bucket = groups.setdefault(gname, {})
            for item in obj:
                if not isinstance(item, str):
                    continue
                k = _tag_collection_line(item)
                if not k or k in existing or k in global_seen:
                    continue
                global_seen.add(k)
                bucket[k] = k
            return
        if isinstance(obj, dict):
            for key, val in obj.items():
                walk(val, group_path + [str(key).strip()])

    walk(data, [])
    return groups


def _collect_packages(
    root: str,
    existing: Set[str],
    global_seen: Set[str],
    lookup: Dict[str, str],
) -> Dict[str, Dict[str, Dict[str, Dict[str, str]]]]:
    per_pack: Dict[str, Dict[str, Dict[str, Dict[str, str]]]] = {}
    for pkg in PACKAGE_YAML_FILES:
        fp = os.path.join(root, pkg)
        if not os.path.isfile(fp):
            continue
        try:
            with open(fp, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except OSError:
            continue
        if not data:
            continue
        pack_name = os.path.splitext(pkg)[0]
        pkg_groups = _parse_yaml_package_tc(data, existing, global_seen)
        for gname, tags in pkg_groups.items():
            if not tags:
                continue
            theme = _theme_for(gname, pack_name)
            if "nsfw" in pack_name.lower() or "sex" in gname.lower():
                theme = "NSFW"
            group_jp = _jp_from_name(gname)
            grp = f"{_pack_label(pack_name)} / {gname}"
            if group_jp and group_jp != gname:
                grp = f"{grp}（{group_jp}）"
            bucket = per_pack.setdefault(pack_name, {}).setdefault(theme, {}).setdefault(grp, {})
            for key in tags:
                if key in existing or key in global_seen:
                    continue
                global_seen.add(key)
                bucket[key] = _resolve_jp(key, group_jp or tags[key], lookup)
    return per_pack


def _merge_pack_trees(
    a: Dict[str, Dict[str, Dict[str, Dict[str, str]]]],
    b: Dict[str, Dict[str, Dict[str, Dict[str, str]]]],
) -> Dict[str, Dict[str, Dict[str, Dict[str, str]]]]:
    out = dict(a)
    for pack, themes in b.items():
        tmap = out.setdefault(pack, {})
        for theme, groups in themes.items():
            gmap = tmap.setdefault(theme, {})
            for group, tags in groups.items():
                bucket = gmap.setdefault(group, {})
                for k, v in tags.items():
                    bucket.setdefault(k, v)
    return out


def _flatten_to_categories(
    per_pack: Dict[str, Dict[str, Dict[str, Dict[str, str]]]],
) -> Dict[str, Dict[str, Dict[str, str]]]:
    """Merge into {theme: {group: {tag: jp}}}."""
    out: Dict[str, Dict[str, Dict[str, str]]] = {}
    for _pack, themes in per_pack.items():
        for theme, groups in themes.items():
            tbucket = out.setdefault(theme, {})
            for group, tags in groups.items():
                gb = tbucket.setdefault(group, {})
                for k, v in tags.items():
                    gb.setdefault(k, v)
    return out


def _build_yaml(categories: Dict[str, Dict[str, Dict[str, str]]]) -> List[Dict]:
    section = {"name": SECTION_NAME, "categories": []}
    theme_order = [label for _, label in THEME_RULES] + ["その他"]
    seen_themes = set()
    for theme in theme_order:
        groups = categories.get(theme)
        if not groups:
            continue
        seen_themes.add(theme)
        cat_obj = {"name": theme, "groups": []}
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
    for theme, groups in sorted(categories.items()):
        if theme in seen_themes or not groups:
            continue
        cat_obj = {"name": theme, "groups": []}
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
    per_pack: Dict[str, Dict[str, Dict[str, Dict[str, str]]]],
    out_dir: str,
    dry_run: bool,
) -> List[Tuple[str, int]]:
    written: List[Tuple[str, int]] = []

    main_packs = {k: v for k, v in per_pack.items() if k not in SPLIT_PACKS}
    jobs: List[Tuple[str, Dict[str, Dict[str, Dict[str, str]]]]] = [
        ("wildcards_tag_collection.yaml", main_packs),
    ]
    for pack, fname in SPLIT_PACKS.items():
        if pack in per_pack:
            jobs.append((fname, {pack: per_pack[pack]}))

    for fname, packs in jobs:
        cats = _flatten_to_categories(packs)
        n = sum(len(t) for g in cats.values() for t in g.values())
        if n == 0:
            continue
        print(f"[tag-collection] {fname}: themes={len(cats)} tags={n}")
        written.append((fname, n))
        if dry_run:
            continue
        path = os.path.join(out_dir, fname)
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                _build_yaml(cats),
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=200,
            )
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
        print(f"[tag-collection] root not found: {root}")
        raise SystemExit(1)

    lookup = _load_jp_lookup(out_dir)
    print(f"[tag-collection] jp lookup keys: {len(lookup)}")

    existing: Set[str] = set()
    for yf in glob.glob(os.path.join(out_dir, "*.yaml")):
        base = os.path.basename(yf)
        if base.startswith("wildcards"):
            continue
        try:
            with open(yf, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or []
        except OSError:
            continue
        if not isinstance(data, list):
            continue
        for sec in data:
            for cat in sec.get("categories", []) or []:
                for grp in cat.get("groups", []) or []:
                    for k in grp.get("tags") or {}:
                        existing.add(str(k))

    global_seen: Set[str] = set()
    per_pack = _collect_txt(root, existing, global_seen, lookup)
    per_pack = _merge_pack_trees(per_pack, _collect_packages(root, existing, global_seen, lookup))

    grand = sum(
        len(tags)
        for pack in per_pack.values()
        for theme in pack.values()
        for tags in theme.values()
    )
    print(f"[tag-collection] packs={len(per_pack)} new_tags={grand}")

    written = _write_outputs(per_pack, out_dir, args.dry_run)

    if not args.dry_run:
        import normalize_tag_spaces as nt

        for fname, _ in written:
            path = os.path.join(out_dir, fname)
            if os.path.isfile(path):
                n = nt.process_file(path)
                print(f"[tag-collection] normalized {fname}: {n} keys")


if __name__ == "__main__":
    main()
