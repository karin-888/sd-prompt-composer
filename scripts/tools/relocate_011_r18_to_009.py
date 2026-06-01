#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Move aieroi R-18 tags from 001/002/003 to 009_NSFW."""

from __future__ import annotations

import glob
import json
import os
import pickle
import sys
from typing import Dict, List, Optional, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
_SECTIONS_DIR = os.path.join(_SCRIPT_DIR, "..", "group_tags", "sections")

SOURCE_FILES = [
    "001_キャラクター.yaml",
    "002_動作_表現.yaml",
    "003_衣装_装飾.yaml",
]
TARGET_FILE = "009_NSFW.yaml"

Dest = Tuple[str, str, str]

# tag_key -> (category, group) in 009_NSFW
R18_DEST: Dict[str, Dest] = {
    "girl_trembling_with_sexual_climax": ("NSFW", "体液・状態"),
    "breast_milk": ("NSFW", "体液・状態"),
    "breast_squeeze": ("NSFW", "乳・乳輪・ピアス"),
    "fellatio_gesture": ("NSFW", "フェラ・イラマチオ・キス"),
    "nipple-to-nipple": ("NSFW", "乳・乳輪・ピアス"),
    "cum_on_armpits": ("NSFW", "精液・愛液"),
    "cum_on_breast": ("NSFW", "精液・愛液"),
    "cum_on_head": ("NSFW", "精液・愛液"),
    "cum_on_tongue": ("NSFW", "精液・愛液"),
    "facial": ("NSFW", "精液・愛液"),
    "bukkake": ("NSFW", "精液・愛液"),
    "cum_in_ass": ("NSFW", "精液・愛液"),
    "cum_on_feet": ("NSFW", "精液・愛液"),
    "projectile_cum": ("NSFW", "精液・愛液"),
    "anal, sex": ("NSFW", "性行為・体位"),
    "supright_straddle": ("NSFW", "性行為・体位"),
    "vaginal, sex": ("NSFW", "性行為・体位"),
    "woman_on_top": ("NSFW", "性行為・体位"),
    "woman_on_top, from_behind": ("NSFW", "性行為・体位"),
    "on_stomach, from_behind": ("NSFW", "性行為・体位"),
    "breasts_blowjob": ("NSFW", "フェラ・イラマチオ・キス"),
    "hairjob": ("NSFW", "フェラ・イラマチオ・キス"),
    "tongue_licking": ("NSFW", "フェラ・イラマチオ・キス"),
    "bottomless": ("NSFW", "服"),
    "topless": ("NSFW", "服"),
    "erect_nipples": ("NSFW", "乳・乳輪・ピアス"),
    "nipple": ("NSFW", "乳・乳輪・ピアス"),
    "show_off_nipple": ("NSFW", "乳・乳輪・ピアス"),
}

# Only move tags whose label matches aieroi import (avoid unrelated homonyms)
AIEROI_LABELS = {
    "girl_trembling_with_sexual_climax": "体を震わせる",
    "breast_milk": "母乳",
    "breast_squeeze": "胸絞り",
    "fellatio_gesture": "フェラチオポーズ",
    "nipple-to-nipple": "乳首合わせ",
    "cum_on_armpits": "腋に射精",
    "cum_on_breast": "胸に射精",
    "cum_on_head": "髪に射精",
    "cum_on_tongue": "舌に射精",
    "facial": "顔に射精",
    "bukkake": "体全体に射精",
    "cum_in_ass": "お尻に射精",
    "cum_on_feet": "足に射精",
    "projectile_cum": "飛ぶ精液",
    "anal, sex": "アナルSEX",
    "supright_straddle": "だいしゅきホールド",
    "vaginal, sex": "挿入(基本)",
    "woman_on_top": "騎乗位",
    "woman_on_top, from_behind": "背面騎乗位",
    "on_stomach, from_behind": "うつ伏せ",
    "breasts_blowjob": "パイズリフェラ",
    "hairjob": "髪コキ",
    "tongue_licking": "亀頭舐め",
    "bottomless": "下半身を裸に",
    "topless": "上半身を裸に",
    "erect_nipples": "胸ポチ(勃起乳首)",
    "nipple": "乳首見せ",
    "show_off_nipple": "乳首見せ",
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


def _remove_tag(section: Dict, tag: str) -> Optional[str]:
    for cat in section.get("categories") or []:
        for grp in cat.get("groups") or []:
            tags = grp.get("tags") or {}
            if tag in tags:
                value = tags.pop(tag)
                return value
    return None


def relocate(*, dry_run: bool = False) -> Dict:
    sections = {f: _load_section(f) for f in SOURCE_FILES + [TARGET_FILE]}
    nsfw = sections[TARGET_FILE]
    stats = {"moved": 0, "not_found": [], "errors": []}

    for tag, (cat_name, group_name) in R18_DEST.items():
        expected_label = AIEROI_LABELS.get(tag)
        found_value = None
        found_in = None
        for fname in SOURCE_FILES:
            for cat in sections[fname].get("categories") or []:
                for grp in cat.get("groups") or []:
                    tags = grp.get("tags") or {}
                    if tag not in tags:
                        continue
                    value = tags[tag]
                    if expected_label and str(value) != expected_label:
                        continue
                    found_value = value
                    found_in = fname
                    break
                if found_value is not None:
                    break
            if found_value is not None:
                break

        if found_value is None:
            stats["not_found"].append(tag)
            continue

        target = _find_group(nsfw, cat_name, group_name)
        if not target:
            stats["errors"].append(f"009/{cat_name}/{group_name} <- {tag}")
            continue

        if not dry_run:
            _remove_tag(sections[found_in], tag)
            target.setdefault("tags", {})[tag] = found_value

        stats["moved"] += 1
        label = f"{found_in} -> 009/{cat_name}/{group_name}"
        stats.setdefault("by_move", {})[label] = stats.get("by_move", {}).get(label, 0) + 1

    if stats["errors"]:
        return stats

    if not dry_run and stats["moved"]:
        for fname in SOURCE_FILES + [TARGET_FILE]:
            _save_section(fname, sections[fname])

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
    print(json.dumps(relocate(dry_run=dry), ensure_ascii=False, indent=2))
