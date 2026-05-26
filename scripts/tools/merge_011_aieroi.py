#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Merge aieroi.com tags from 011 into core sections 000-008."""

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

SOURCE_FILE = "011_aiエロイラスト_com_aieroi_com.yaml"

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

CAT_GROUP_MAP: Dict[Tuple[str, str], Dest] = {
    # 003 衣装
    ("コスチューム", "コスチューム"): ("003_衣装_装飾.yaml", "衣装", "コスチューム・特殊衣装"),
    ("コスチューム", "コスプレ衣装、他"): ("003_衣装_装飾.yaml", "衣装", "コスチューム・特殊衣装"),
    ("コスチューム", "民族衣装"): ("003_衣装_装飾.yaml", "衣装", "民族衣装"),
    ("下着", "その他(ランジェリーなど)"): ("003_衣装_装飾.yaml", "衣装", "カジュアル・部屋着"),
    ("下着", "下着"): ("003_衣装_装飾.yaml", "衣装", "カジュアル・部屋着"),
    ("装飾品", "その他(帽子など)"): ("003_衣装_装飾.yaml", "衣服や装飾品", "帽子"),
    ("装飾品", "髪"): ("003_衣装_装飾.yaml", "衣装", "髪飾り・頭飾り"),
    ("着衣エロ", "着衣エロ(全般/下半身)"): ("009_NSFW.yaml", "NSFW", "服"),
    ("着衣エロ", "着衣エロ(胸/上半身)"): ("009_NSFW.yaml", "NSFW", "服"),
    ("R-18エロ強化", "エロ演出"): ("009_NSFW.yaml", "NSFW", "体液・状態"),
    ("R-18エロ強化", "他、エロ描写"): ("009_NSFW.yaml", "NSFW", "乳・乳輪・ピアス"),
    ("射精", "射精(上半身)"): ("009_NSFW.yaml", "NSFW", "精液・愛液"),
    ("射精", "射精(下半身/その他)"): ("009_NSFW.yaml", "NSFW", "精液・愛液"),
    ("SEX体位", "SEX(体位など)"): ("009_NSFW.yaml", "NSFW", "性行為・体位"),
    ("SEX体位", "その他体位(ポーズを指定)"): ("009_NSFW.yaml", "NSFW", "性行為・体位"),
    ("前戯", "オーラル行為"): ("009_NSFW.yaml", "NSFW", "フェラ・イラマチオ・キス"),
    # 002 動作
    ("ポーズ・基本", "動的ポーズ"): ("002_動作_表現.yaml", "基本動作・ポーズ", "移動・運動"),
    ("ポーズ・基本", "基本ポーズ"): ("002_動作_表現.yaml", "基本動作・ポーズ", "基本姿勢"),
    ("ポーズ・手足", "手のポーズ"): ("002_動作_表現.yaml", "基本動作・ポーズ", "手の動き・ジェスチャー"),
    ("ポーズ・手足", "足のポーズ"): ("002_動作_表現.yaml", "基本動作・ポーズ", "脚の動き・姿勢"),
    # 006 背景
    ("背景・室内", "その他"): ("006_背景_環境.yaml", "シーン", "屋内"),
    ("背景・室内", "室内"): ("006_背景_環境.yaml", "シーン", "屋内"),
    ("背景・室内", "施設"): ("006_背景_環境.yaml", "シーン", "屋内"),
    ("背景・屋外", "その他"): ("006_背景_環境.yaml", "背景", "背景色・効果"),
    ("背景・屋外", "屋外施設"): ("006_背景_環境.yaml", "シーン", "屋外"),
    ("背景・屋外", "自然"): ("006_背景_環境.yaml", "植物・自然", "植物"),
}

TAG_MAP: Dict[str, Dest] = {
    "battoujutsu_stance": ("002_動作_表現.yaml", "基本動作・ポーズ", "戦闘・格闘"),
    "weapon_shop": ("005_小物_道具.yaml", "アイテム", "武器"),
    "superhero": ("003_衣装_装飾.yaml", "衣装", "コスチューム・特殊衣装"),
    "erect_nipples": ("009_NSFW.yaml", "NSFW", "乳・乳輪・ピアス"),
    "nipple": ("009_NSFW.yaml", "NSFW", "乳・乳輪・ピアス"),
    "show_off_nipple": ("009_NSFW.yaml", "NSFW", "乳・乳輪・ピアス"),
    "breast_milk": ("009_NSFW.yaml", "NSFW", "体液・状態"),
    "breast_squeeze": ("009_NSFW.yaml", "NSFW", "乳・乳輪・ピアス"),
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
    return ("002_動作_表現.yaml", "基本動作・ポーズ", "特殊なポーズ・表現")


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
