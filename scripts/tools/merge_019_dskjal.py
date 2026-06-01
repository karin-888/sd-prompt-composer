#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Merge dskjal.com tags from 019 into core sections 000-009."""

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

SOURCE_FILE = "019_よく検索されているプロンプト_dskjal_com.yaml"

TARGET_FILES = [
    "000_画像品質_技術.yaml",
    "001_キャラクター.yaml",
    "002_動作_表現.yaml",
    "003_衣装_装飾.yaml",
    "004_視覚効果.yaml",
    "005_小物_道具.yaml",
    "006_背景_環境.yaml",
    "007_食べ物.yaml",
    "008_ジャンル_世界観.yaml",
    "009_NSFW.yaml",
]

Dest = Tuple[str, str, str]

# (category, group) -> dest; group None = default for category
CAT_GROUP_MAP: Dict[Tuple[str, Optional[str]], Dest] = {
    ("体位・プレイ", "体位・プレイ"): ("009_NSFW.yaml", "NSFW", "体位・プレイ"),
    ("体位・プレイ", "乳系プレイ"): ("009_NSFW.yaml", "NSFW", "乳・乳輪・ピアス"),
    ("体位・プレイ", "複数人"): ("009_NSFW.yaml", "NSFW", "特殊・シチュエーション"),
    ("体位・プレイ", "ポーズ"): ("009_NSFW.yaml", "NSFW", "動作・ポーズ"),
    ("体位・プレイ", "オナニー女"): ("009_NSFW.yaml", "NSFW", "特殊・シチュエーション"),
    ("エロ衣装", "エロ全身"): ("009_NSFW.yaml", "NSFW", "服"),
    ("エロ衣装", "エロ上半身"): ("009_NSFW.yaml", "NSFW", "服"),
    ("ハンドサイン", "ハンドサイン"): ("009_NSFW.yaml", "NSFW", "ハンドサイン"),
    ("男", "男"): ("009_NSFW.yaml", "NSFW", "特殊・シチュエーション"),
    ("尻", "尻"): ("009_NSFW.yaml", "NSFW", "アヌス・尻穴"),
    ("BDSM", "BDSM"): ("009_NSFW.yaml", "NSFW", "緊縛・BDSM"),
    ("オホ顔", "オホ顔"): ("009_NSFW.yaml", "NSFW", "表情・顔"),
    ("性的な表情", "性的な表情"): ("009_NSFW.yaml", "NSFW", "表情・顔"),
    ("脚と足", "脚と足"): ("003_衣装_装飾.yaml", "衣装", "靴下"),
    ("靴", "靴"): ("003_衣装_装飾.yaml", "衣装", "靴"),
    ("一般ポーズ", "一般ポーズ"): ("002_動作_表現.yaml", "基本動作・ポーズ", "特殊なポーズ・表現"),
    ("脚のポーズ", "脚のポーズ"): ("002_動作_表現.yaml", "基本動作・ポーズ", "脚の動き・姿勢"),
    ("アングル", "アングル"): ("004_視覚効果.yaml", "アングル・構図", "視点・角度"),
    ("表情", "特殊形状"): ("002_動作_表現.yaml", "表情動作", "その他表情"),
    ("表情", "咥え"): ("002_動作_表現.yaml", "表情動作", "その他表情"),
    ("表情", "食べ物"): ("007_食べ物.yaml", "食べ物・飲み物", "食べ物・飲み物"),
    ("表情", "口BDSM"): ("009_NSFW.yaml", "NSFW", "表情・顔"),
}

TAG_MAP: Dict[str, Dest] = {
    "electric_eyes": ("004_視覚効果.yaml", "画面", "芸術スタイル"),
    "holding_cum": ("009_NSFW.yaml", "NSFW", "体液・状態"),
    "ballet_dress": ("003_衣装_装飾.yaml", "衣装", "コスチューム・特殊衣装"),
    "detatched_pants": ("003_衣装_装飾.yaml", "衣装", "ボトムス"),
    "honggaitou": ("003_衣装_装飾.yaml", "衣装", "髪飾り・頭飾り"),
    "mongkhon": ("003_衣装_装飾.yaml", "衣装", "髪飾り・頭飾り"),
    "stringer": ("003_衣装_装飾.yaml", "衣装", "シャツ"),
    "disppointed": ("002_動作_表現.yaml", "表情動作", "その他表情"),
    "fake_eyelashes": ("001_キャラクター.yaml", "顔パーツ", "目の形状"),
    "glass_eye": ("001_キャラクター.yaml", "顔パーツ", "目の形状"),
    "looking_at_crotch": ("009_NSFW.yaml", "NSFW", "表情・顔"),
    "mole_over_mouth": ("001_キャラクター.yaml", "顔パーツ", "唇"),
    "moon-shaped_pupils": ("001_キャラクター.yaml", "顔パーツ", "瞳孔"),
    "p": ("002_動作_表現.yaml", "表情動作", "その他表情"),
    "partially_blind": ("001_キャラクター.yaml", "顔パーツ", "目の形状"),
    "snowflakes-shaped_pupils": ("001_キャラクター.yaml", "顔パーツ", "瞳孔"),
    "c": ("002_動作_表現.yaml", "表情動作", "その他表情"),
    "I": ("002_動作_表現.yaml", "表情動作", "その他表情"),
    "t": ("002_動作_表現.yaml", "表情動作", "その他表情"),
    "atmospheric_reentry": ("004_視覚効果.yaml", "画面", "芸術スタイル"),
    "twinkle_in_the_sky": ("004_視覚効果.yaml", "画面", "芸術スタイル"),
    "center_axis_relock_stance": ("002_動作_表現.yaml", "基本動作・ポーズ", "戦闘・格闘"),
    "gatotsu_stance": ("002_動作_表現.yaml", "基本動作・ポーズ", "戦闘・格闘"),
    "ox_guard": ("002_動作_表現.yaml", "基本動作・ポーズ", "戦闘・格闘"),
    "hand_to_blade": ("002_動作_表現.yaml", "基本動作・ポーズ", "戦闘・格闘"),
    "sheathed_cut": ("002_動作_表現.yaml", "基本動作・ポーズ", "戦闘・格闘"),
    "swinging_weapon": ("002_動作_表現.yaml", "基本動作・ポーズ", "戦闘・格闘"),
    "ice_sword": ("005_小物_道具.yaml", "アイテム", "武器"),
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


def _existing_keys(sections: Dict[str, Dict]) -> Dict[str, Dest]:
    out: Dict[str, Dest] = {}
    for fname, section in sections.items():
        if fname == SOURCE_FILE:
            continue
        for cat in section.get("categories") or []:
            cn = cat.get("name") or ""
            if cn.startswith("noplog ·"):
                continue
            for grp in cat.get("groups") or []:
                gn = grp.get("name") or ""
                for k in (grp.get("tags") or {}):
                    out[_tag_key(str(k))] = (fname, cn, gn)
    return out


def _map_dest(cat_name: str, group_name: str, tag: str) -> Dest:
    if tag in TAG_MAP:
        return TAG_MAP[tag]
    key = (cat_name, group_name)
    if key in CAT_GROUP_MAP:
        return CAT_GROUP_MAP[key]
    if (cat_name, None) in CAT_GROUP_MAP:
        return CAT_GROUP_MAP[(cat_name, None)]

    if cat_name == "頭":
        return ("003_衣装_装飾.yaml", "衣装", "髪飾り・頭飾り")
    if cat_name == "エフェクト":
        return ("004_視覚効果.yaml", "画面", "芸術スタイル")
    if cat_name == "表情":
        return ("002_動作_表現.yaml", "表情動作", "その他表情")
    if cat_name == "一般エフェクト":
        return ("004_視覚効果.yaml", "画面", "芸術スタイル")

    return ("009_NSFW.yaml", "NSFW", "特殊・シチュエーション")


def merge(*, dry_run: bool = False) -> Dict:
    sections = {f: _load_section(f) for f in TARGET_FILES}
    existing = _existing_keys(sections)
    stats = {"added": 0, "skipped": 0, "by_target": {}, "errors": []}

    source = _load_section(SOURCE_FILE)
    for cat in source.get("categories") or []:
        cn = cat.get("name") or ""
        for grp in cat.get("groups") or []:
            gn = grp.get("name") or ""
            for key, value in (grp.get("tags") or {}).items():
                nk = _tag_key(str(key))
                if not nk:
                    continue
                if nk in existing:
                    stats["skipped"] += 1
                    continue
                fname, cat_name, group_name = _map_dest(cn, gn, str(key))
                target = _find_group(sections[fname], cat_name, group_name)
                if not target:
                    stats["errors"].append(f"{fname}/{cat_name}/{group_name} <- {cn}/{gn}/{key}")
                    continue
                if not dry_run:
                    target.setdefault("tags", {})[str(key)] = value
                existing[nk] = (fname, cat_name, group_name)
                stats["added"] += 1
                label = f"{fname}/{cat_name}/{group_name}"
                stats["by_target"][label] = stats["by_target"].get(label, 0) + 1

    if stats["errors"]:
        stats["errors"] = stats["errors"][:30]
        return stats

    if not dry_run:
        for fname in TARGET_FILES:
            _save_section(fname, sections[fname])
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
    result = merge(dry_run=dry)
    print(json.dumps(result, ensure_ascii=False, indent=2))
