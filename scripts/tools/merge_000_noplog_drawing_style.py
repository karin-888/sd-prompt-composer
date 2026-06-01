#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Merge noplog drawing/expression style tags from 000 into core sections."""

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

SOURCE_FILE = "000_画像品質_技術.yaml"
SOURCE_NOPLOG = "noplog · 【AIイラスト】Stable Diffusion 2400プロンプト完全網羅！"
SOURCE_GROUPS = {"２-１．描画スタイル", "２-２．表現スタイル"}

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
]

# tag -> (category, group)
TAG_MAP: Dict[str, Tuple[str, str]] = {
    # ２-１．描画スタイル
    "acrylic_painting": ("画面", "ペン"),
    "airbrush": ("画面", "芸術の種類"),
    "artistic_portrait": ("画面", "芸術スタイル"),
    "black_outline": ("画面", "スケッチ"),
    "chalk": ("画面", "ペン"),
    "charcoal_drawing": ("画面", "ペン"),
    "clay_animation_style": ("画面", "芸術スタイル"),
    "clay_render": ("画面", "芸術スタイル"),
    "colored_pencil": ("画面", "ペン"),
    "coloring_book": ("画面", "芸術スタイル"),
    "coupy_pencil": ("画面", "ペン"),
    "crayon": ("画面", "ペン"),
    "dreamy_watercolor": ("画面", "芸術スタイル"),
    "flat_design": ("画面", "スケッチ"),
    "ink_drawing": ("画面", "芸術の種類"),
    "ink_painting": ("画面", "芸術の種類"),
    "line_art": ("画面", "芸術スタイル"),
    "marker_style": ("画面", "ペン"),
    "millipen_style": ("画面", "ペン"),
    "paper_cutout_art": ("画面", "芸術の種類"),
    "pastel_painting": ("画面", "ペン"),
    "pencil_drawing": ("画面", "ペン"),
    "pointillism": ("画面", "芸術派"),
    "scattered_painting": ("画面", "芸術スタイル"),
    "sharp_sketch": ("画面", "スケッチ"),
    "silhouette_style": ("画面", "芸術スタイル"),
    "sketch_style": ("画面", "芸術スタイル"),
    "thick_outline": ("画面", "スケッチ"),
    "watercolor_painting": ("画面", "芸術の種類"),
    "watercolor_pencil": ("画面", "ペン"),
    # ２-２．表現スタイル
    "3d_effect": ("画面", "画質"),
    "animated_painting": ("画面", "芸術スタイル"),
    "anime_colored": ("画面", "芸術スタイル"),
    "autochrome": ("画面", "リアル"),
    "cartoon": ("画面", "芸術スタイル"),
    "cel_anime": ("画面", "芸術スタイル"),
    "film_grain": ("画面", "リアル"),
    "glitch_effect": ("アングル・構図", "レンズ・効果"),
    "graffiti": ("画面", "芸術スタイル"),
    "high_definition_art": ("クオリティ", "品質・解像度"),
    "hyperrealistic": ("クオリティ", "品質・解像度"),
    "isometric": ("アングル・構図", "視点・角度"),
    "manga_style": ("画面", "芸術スタイル"),
    "monochromatic": ("画面", "スケッチ"),
    "oekaki": ("画面", "芸術スタイル"),
    "photograph": ("画面", "リアル"),
    "retro_style": ("画面", "芸術スタイル"),
    "sepia": ("画面", "リアル"),
    "snapshot": ("画面", "リアル"),
    "vibrant_colors": ("画面", "画質"),
    "vintage_photograph": ("画面", "リアル"),
}


def _tag_key(tag: str) -> str:
    return (tag or "").strip().lower()


def _load_section(filename: str) -> Dict:
    path = os.path.join(_SECTIONS_DIR, filename)
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    return data[0] if isinstance(data, list) else {}


def _save_section(filename: str, section: Dict) -> None:
    path = os.path.join(_SECTIONS_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump([section], f, allow_unicode=True, sort_keys=False, width=120)


def _find_group(section: Dict, cat_name: str, group_name: str) -> Optional[Dict]:
    for cat in section.get("categories") or []:
        if (cat.get("name") or "") != cat_name:
            continue
        for grp in cat.get("groups") or []:
            if (grp.get("name") or "") == group_name:
                return grp
    return None


def _existing_keys(sections: Dict[str, Dict]) -> Dict[str, Tuple[str, str, str]]:
    out: Dict[str, Tuple[str, str, str]] = {}
    for fname, section in sections.items():
        for cat in section.get("categories") or []:
            cn = cat.get("name") or ""
            if cn.startswith("noplog ·"):
                continue
            for grp in cat.get("groups") or []:
                gn = grp.get("name") or ""
                for k in (grp.get("tags") or {}):
                    out[_tag_key(str(k))] = (fname, cn, gn)
    return out


def _target_file(cat_name: str) -> str:
    if cat_name == "クオリティ":
        return "000_画像品質_技術.yaml"
    return "004_視覚効果.yaml"


def merge() -> Dict:
    sections = {f: _load_section(f) for f in TARGET_FILES}
    existing = _existing_keys(sections)
    stats = {"added": 0, "skipped": 0, "by_target": {}, "missing": []}

    source = sections[SOURCE_FILE]
    source_cat = None
    for cat in source.get("categories") or []:
        if (cat.get("name") or "") == SOURCE_NOPLOG:
            source_cat = cat
            break
    if not source_cat:
        return {"error": "source noplog category not found"}

    for grp in source_cat.get("groups") or []:
        gn = grp.get("name") or ""
        if gn not in SOURCE_GROUPS:
            continue
        for key, value in (grp.get("tags") or {}).items():
            nk = _tag_key(str(key))
            if not nk:
                continue
            if nk in existing:
                stats["skipped"] += 1
                continue
            dest = TAG_MAP.get(str(key))
            if not dest:
                stats["missing"].append(str(key))
                continue
            cat_name, group_name = dest
            fname = _target_file(cat_name)
            target = _find_group(sections[fname], cat_name, group_name)
            if not target:
                raise RuntimeError(f"Missing group: {fname}/{cat_name}/{group_name}")
            target.setdefault("tags", {})[str(key)] = value
            existing[nk] = (fname, cat_name, group_name)
            stats["added"] += 1
            label = f"{fname}/{cat_name}/{group_name}"
            stats["by_target"][label] = stats["by_target"].get(label, 0) + 1

    source["categories"] = [
        c for c in (source.get("categories") or [])
        if (c.get("name") or "") != SOURCE_NOPLOG
    ]

    for fname in TARGET_FILES:
        _save_section(fname, sections[fname])

    sys.path.insert(0, _TOOLS_DIR)
    from split_default_by_section import _collect_paths_and_index

    group_tags_dir = os.path.join(_SCRIPT_DIR, "..", "group_tags")
    files = sorted(glob.glob(os.path.join(group_tags_dir, "sections", "*.yaml")))
    manifest_sections = []
    search_index: List[Dict] = []
    seen_index = set()
    all_paths: List[Dict] = []
    all_path_counts: Dict[str, int] = {}
    all_path_entries: List[Dict] = []

    for rel_file in files:
        rel = os.path.join("sections", os.path.basename(rel_file)).replace("\\", "/")
        with open(rel_file, encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
        if not data:
            continue
        sec = data[0] if isinstance(data, list) else data
        paths, path_counts, path_entries, rows = _collect_paths_and_index(sec)
        tag_count = 0
        for row in rows:
            key = _tag_key(row.get("tag") or "")
            if not key or key in seen_index:
                continue
            seen_index.add(key)
            search_index.append(row)
            tag_count += 1
        all_paths.extend(paths)
        for k, v in path_counts.items():
            all_path_counts[k] = all_path_counts.get(k, 0) + v
        all_path_entries.extend(path_entries)
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
        "paths": all_paths,
        "pathCounts": all_path_counts,
        "pathEntries": all_path_entries,
    }
    with open(os.path.join(group_tags_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    with open(os.path.join(group_tags_dir, "search-index.pkl"), "wb") as f:
        pickle.dump({"version": 2, "source_mtime": 0, "rows": search_index}, f, protocol=pickle.HIGHEST_PROTOCOL)

    stats["manifest_tags"] = len(search_index)
    return stats


if __name__ == "__main__":
    print(merge())
