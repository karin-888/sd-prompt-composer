#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Merge NovelAI / Illustrious recommended tags from 027 into core sections 000-009."""

from __future__ import annotations

import json
import os
import sys
from typing import Dict, Optional, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
_SECTIONS_DIR = os.path.join(_SCRIPT_DIR, "..", "group_tags", "sections")

SOURCE_FILE = "027_novelai_illustrious_推奨タグ.yaml"

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

NEG_IMAGE_TAGS = {
    "bad quality", "worst quality", "very displeasing", "low quality",
    "jpeg artifacts", "out of frame",
}

NEG_PERSON_TAGS = {
    "bad anatomy", "bad fingers", "bad hands", "extra digits", "extra fingers",
    "extra limbs", "fewer digits", "long neck", "missing arms", "missing legs",
    "morbid", "mutilated",
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


def _map_dest(cat_name: str, tag: str) -> Dest:
    cn = cat_name or ""
    tk = _tag_key(tag)

    if "推奨品質トークン" in cn or "推奨レーティング" in cn:
        return ("000_画像品質_技術.yaml", "クオリティ", "品質・解像度")

    if cn == "NovelAI v3 推奨品質トークン":
        if tk in {"bad quality", "worst quality", "very displeasing"}:
            return ("000_画像品質_技術.yaml", "ネガティブ", "画像品質")
        return ("000_画像品質_技術.yaml", "クオリティ", "品質・解像度")

    if cn == "ネガティブプロンプト定番":
        if tk in NEG_IMAGE_TAGS:
            return ("000_画像品質_技術.yaml", "ネガティブ", "画像品質")
        if tk in NEG_PERSON_TAGS:
            return ("000_画像品質_技術.yaml", "ネガティブ", "人物の問題")
        return ("000_画像品質_技術.yaml", "ネガティブ", "画像品質")

    if cn == "構図・人数の基本":
        return ("004_視覚効果.yaml", "アングル・構図", "視点・角度")

    return ("000_画像品質_技術.yaml", "クオリティ", "品質・解像度")


def merge(*, dry_run: bool = False) -> Dict:
    sections = {f: _load_section(f) for f in TARGET_FILES}
    existing = _existing_keys(sections)
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
                target = _find_group(sections[fname], cat_name, group_name)
                if not target:
                    stats["errors"].append(f"{fname}/{cat_name}/{group_name} <- {cn}/{key}")
                    continue
                if not dry_run:
                    target.setdefault("tags", {})[str(key)] = value
                existing[nk] = (fname, cat_name, group_name)
                stats["added"] += 1
                label = f"{fname}/{cat_name}/{group_name}"
                stats["by_target"][label] = stats["by_target"].get(label, 0) + 1

    if stats["errors"]:
        stats["errors"] = stats["errors"][:25]
        return stats

    if not dry_run:
        for fname in TARGET_FILES:
            _save_section(fname, sections[fname])
        os.remove(os.path.join(_SECTIONS_DIR, SOURCE_FILE))
        sys.path.insert(0, _TOOLS_DIR)
        from rebuild_manifest import rebuild
        stats["manifest"] = rebuild()

    return stats


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    print(json.dumps(merge(dry_run=dry), ensure_ascii=False, indent=2))
