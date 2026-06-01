#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Merge mania.romptn.com tags from 023 into 009_NSFW."""

from __future__ import annotations

import glob
import json
import os
import pickle
import re
import sys
from typing import Dict, List, Optional, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
_SECTIONS_DIR = os.path.join(_SCRIPT_DIR, "..", "group_tags", "sections")

SOURCE_FILE = "023_エロ系プロンプト一覧_mania_romptn_com.yaml"
TARGET_FILE = "009_NSFW.yaml"

Dest = Tuple[str, str, str]

CAT_DEFAULT: Dict[str, Dest] = {
    "体位": ("009_NSFW.yaml", "NSFW", "性行為・体位"),
    "ポーズ・体勢": ("009_NSFW.yaml", "NSFW", "動作・ポーズ"),
    "前戯": ("009_NSFW.yaml", "NSFW", "フェラ・イラマチオ・キス"),
    "複数プレイ": ("009_NSFW.yaml", "NSFW", "特殊・シチュエーション"),
    "胸・乳首": ("009_NSFW.yaml", "NSFW", "乳・乳輪・ピアス"),
    "体型": ("009_NSFW.yaml", "NSFW", "身体部位"),
    "パンツ": ("009_NSFW.yaml", "NSFW", "服"),
    "ブラジャー": ("009_NSFW.yaml", "NSFW", "服"),
    "表情": ("009_NSFW.yaml", "NSFW", "表情・顔"),
    "衣装": ("009_NSFW.yaml", "NSFW", "服"),
    "SM": ("009_NSFW.yaml", "NSFW", "緊縛・BDSM"),
    "アダルトグッズ": ("009_NSFW.yaml", "NSFW", "性玩具・道具"),
    "シチュエーション": ("009_NSFW.yaml", "NSFW", "特殊・シチュエーション"),
}


def _tag_key(tag: str) -> str:
    return (tag or "").strip().lower()


def _load_section(filename: str) -> Dict:
    with open(os.path.join(_SECTIONS_DIR, filename), encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    return data[0] if isinstance(data, list) else {}


def _save_section(filename: str, section: Dict) -> None:
    with open(os.path.join(_SECTIONS_DIR, filename), "w", encoding="utf-8") as f:
        yaml.dump([section], f, allow_unicode=True, sort_keys=False, width=120)


def _find_group(section: Dict, cat_name: str, group_name: str) -> Optional[Dict]:
    for cat in section.get("categories") or []:
        if (cat.get("name") or "") != cat_name:
            continue
        for grp in cat.get("groups") or []:
            if (grp.get("name") or "") == group_name:
                return grp
    return None


def _existing_keys(section: Dict) -> Dict[str, Dest]:
    out: Dict[str, Dest] = {}
    for cat in section.get("categories") or []:
        cn = cat.get("name") or ""
        for grp in cat.get("groups") or []:
            gn = grp.get("name") or ""
            for k in (grp.get("tags") or {}):
                out[_tag_key(str(k))] = (TARGET_FILE, cn, gn)
    return out


def _genital_dest(tag: str) -> Dest:
    t = tag.lower()
    if re.search(r"(cock|penis|balls|throat_cock|veiny_cock|erect_cock|huge_cock|small_cock|monster_cock|throbbing_cock|cum_dripping_cock)", t):
        return ("009_NSFW.yaml", "NSFW", "ペニス")
    if re.search(r"(anal|ass_to|gape.*anal|double_penetration_anus)", t):
        return ("009_NSFW.yaml", "NSFW", "アヌス・尻穴")
    return ("009_NSFW.yaml", "NSFW", "女性器")


def _fluid_dest(tag: str) -> Dest:
    t = tag.lower()
    if re.search(r"(urine|pee|_pee|light_pee)", t):
        return ("009_NSFW.yaml", "NSFW", "おしっこ・放尿・おもらし")
    if re.search(r"(cum|semen|creampie|bukkake|facial|squirt|milk_spray|spraying_milk|snowball)", t):
        return ("009_NSFW.yaml", "NSFW", "精液・愛液")
    return ("009_NSFW.yaml", "NSFW", "体液・状態")


def _foreplay_dest(tag: str) -> Dest:
    t = tag.lower()
    if re.search(r"(vibrator|dildo|plug|butt_plug)", t):
        return ("009_NSFW.yaml", "NSFW", "性玩具・道具")
    if re.search(r"(spanking|blindfold|breath_play|wax_drip|clamp|tickle|ice_cube)", t):
        return ("009_NSFW.yaml", "NSFW", "緊縛・BDSM")
    if re.search(r"(handjob|fingering|thighjob|massage|rubbing|prostate|edging)", t):
        return ("009_NSFW.yaml", "NSFW", "動作・ポーズ")
    return ("009_NSFW.yaml", "NSFW", "フェラ・イラマチオ・キス")


def _map_dest(cat_name: str, tag: str) -> Dest:
    if cat_name == "陰部":
        return _genital_dest(tag)
    if cat_name == "体液":
        return _fluid_dest(tag)
    if cat_name == "前戯":
        return _foreplay_dest(tag)
    if cat_name in CAT_DEFAULT:
        return CAT_DEFAULT[cat_name]
    return ("009_NSFW.yaml", "NSFW", "特殊・シチュエーション")


def merge(*, dry_run: bool = False) -> Dict:
    target = _load_section(TARGET_FILE)
    existing = _existing_keys(target)
    stats = {"added": 0, "skipped": 0, "by_target": {}, "errors": []}

    source = _load_section(SOURCE_FILE)
    for cat in source.get("categories") or []:
        cn = cat.get("name") or ""
        for grp in cat.get("groups") or []:
            for key, value in (grp.get("tags") or {}).items():
                nk = _tag_key(str(key))
                if not nk:
                    continue
                if nk in existing:
                    stats["skipped"] += 1
                    continue
                fname, cat_name, group_name = _map_dest(cn, str(key))
                group = _find_group(target, cat_name, group_name)
                if not group:
                    stats["errors"].append(f"{fname}/{cat_name}/{group_name} <- {cn}/{key}")
                    continue
                if not dry_run:
                    group.setdefault("tags", {})[str(key)] = value
                existing[nk] = (fname, cat_name, group_name)
                stats["added"] += 1
                label = f"{cat_name}/{group_name}"
                stats["by_target"][label] = stats["by_target"].get(label, 0) + 1

    if stats["errors"]:
        stats["errors"] = stats["errors"][:20]
        return stats

    if not dry_run:
        _save_section(TARGET_FILE, target)
        os.remove(os.path.join(_SECTIONS_DIR, SOURCE_FILE))

        sys.path.insert(0, _TOOLS_DIR)
        from split_default_by_section import _collect_paths_and_index

        group_tags_dir = os.path.join(_SCRIPT_DIR, "..", "group_tags")
        files = sorted(glob.glob(os.path.join(group_tags_dir, "sections", "*.yaml")))
        manifest_sections = []
        search_index: List[Dict] = []
        seen_index = set()

        for rel_file in files:
            rel = os.path.join("sections", os.path.basename(rel_file)).replace("\\", "/")
            with open(rel_file, encoding="utf-8") as f:
                data = yaml.safe_load(f) or []
            if not data:
                continue
            sec = data[0] if isinstance(data, list) else data
            _, _, _, rows = _collect_paths_and_index(sec)
            tag_count = 0
            for row in rows:
                key = _tag_key(row.get("tag") or "")
                if not key or key in seen_index:
                    continue
                seen_index.add(key)
                search_index.append(row)
                tag_count += 1
            manifest_sections.append({
                "name": sec.get("name") or "",
                "file": rel,
                "tagCount": tag_count,
                "categoryCount": len(sec.get("categories") or []),
            })

        manifest = {
            "version": 2,
            "source": "default.yaml",
            "sectionCount": len(manifest_sections),
            "tagCount": len(search_index),
            "sections": manifest_sections,
        }
        with open(os.path.join(group_tags_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        with open(os.path.join(group_tags_dir, "search-index.pkl"), "wb") as f:
            pickle.dump(search_index, f)

    return stats


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    print(json.dumps(merge(dry_run=dry), ensure_ascii=False, indent=2))
