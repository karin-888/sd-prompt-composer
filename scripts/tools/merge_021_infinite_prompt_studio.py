#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Merge INFINITE PROMPT STUDIO tags from 021 into core sections 000-009."""

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

SOURCE_FILE = "021_infinite_prompt_studio.yaml"

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

THEME_CAT = {
    "水着": "水着",
    "制服": "制服",
    "メイド": "コスチューム・特殊衣装",
    "コスプレ": "コスチューム・特殊衣装",
    "和服": "和服",
    "チャイナ": "民族衣装",
    "巫女": "和服",
    "忍者": "コスチューム・特殊衣装",
    "パジャマ": "カジュアル・部屋着",
    "部屋着": "カジュアル・部屋着",
    "メカ": "コスチューム・特殊衣装",
    "VTuber": "コスチューム・特殊衣装",
    "シスター": "コスチューム・特殊衣装",
    "ナース": "制服",
    "バニー": "コスチューム・特殊衣装",
    "レースクイーン": "コスチューム・特殊衣装",
    "RPG": "コスチューム・特殊衣装",
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


def _nsfw_group_from_name(group_name: str) -> str:
    g = (group_name or "").lower()
    if "expression" in g and "pose" not in g:
        return "表情・顔"
    if "sex act" in g or "sex poses" in g or "positionpack" in g:
        return "性行為・体位"
    if "pose" in g or "position" in g:
        return "動作・ポーズ" if "sex" not in g else "性行為・体位"
    if "genitals" in g:
        return "女性器"
    if "anus" in g:
        return "アヌス・尻穴"
    if "nipple" in g or "breast" in g:
        return "乳・乳輪・ピアス"
    if "fluid" in g:
        return "体液・状態"
    if "bondage" in g:
        return "緊縛・BDSM"
    if any(k in g for k in ("tops", "inners", "outers", "bottoms", "socks", "shoes", " acc", "/acc", "clothing", "lingerie", "underwear", "bra", "pants")):
        return "服"
    if g in {"tops", "inners", "outers", "bottoms", "socks", "shoes", "acc"}:
        return "服"
    if "situation" in g or "partner" in g or "insertion" in g or "lighting" in g or "camera" in g:
        return "特殊・シチュエーション"
    return "特殊・シチュエーション"


def _fashion_group_dest(group_name: str) -> Dest:
    gn = group_name or ""
    g = gn.lower()
    if gn in {"Tops", "Vtuber / Tops", "Samurai / Tops"} or g.endswith("/ tops"):
        return ("003_衣装_装飾.yaml", "衣装", "シャツ")
    if gn in {"Bottoms", "Pants", "Vtuber / Bottoms", "Samurai / Bottoms"} or "/ bottoms" in g:
        return ("003_衣装_装飾.yaml", "衣装", "ボトムス")
    if gn in {"Outers", "Outerwear", "Vtuber / Outerwear", "Samurai / Outers"} or "/ outers" in g or "outerwear" in g:
        return ("003_衣装_装飾.yaml", "衣装", "アウター")
    if gn in {"Socks", "Vtuber / Socks", "Samurai / Socks"} or "/ socks" in g:
        return ("003_衣装_装飾.yaml", "衣装", "靴下")
    if gn in {"Shoes", "Vtuber / Shoes", "Samurai / Shoes"} or "/ shoes" in g:
        return ("003_衣装_装飾.yaml", "衣装", "靴")
    if gn in {"Acc", "Headacc", "Vtuber / Acc", "Samurai / Acc"} or gn.endswith(" / Acc") or g.endswith("/ acc"):
        return ("003_衣装_装飾.yaml", "衣装", "アクセサリー・小物")
    if gn in {"Inners", "Bra", "Vtuber / Inners", "Samurai / Inners"} or "/ inners" in g:
        return ("003_衣装_装飾.yaml", "衣装", "カジュアル・部屋着")
    if gn in {"Presets", "Styles", "Variationsets", "Layertemplates"}:
        return ("003_衣装_装飾.yaml", "衣服や装飾品", "スタイル")
    return ("003_衣装_装飾.yaml", "衣装", "シャツ")


def _fashion_dest(cat_name: str, group_name: str) -> Dest:
    for theme, grp in THEME_CAT.items():
        if theme in cat_name:
            base = _fashion_group_dest(group_name)
            if base[2] in {"シャツ", "ボトムス", "アウター", "靴下", "靴", "アクセサリー・小物", "カジュアル・部屋着"}:
                return (base[0], base[1], grp)
    return _fashion_group_dest(group_name)


def _hair_group(group_name: str) -> str:
    g = (group_name or "").lower()
    if "length" in g:
        return "長さ"
    if "color" in g:
        return "髪の色"
    if "style" in g or "hairstyle" in g:
        return "特殊な髪型"
    if "eye shape" in g or g == "eye shapes":
        return "目の形状"
    if "eye color" in g or g == "eye colors":
        return "目の色"
    return "特殊な髪型"


def _map_dest(cat_name: str, group_name: str) -> Dest:
    cn, gn = cat_name or "", group_name or ""
    g = gn.lower()

    if cn.startswith("R18") or cn == "共通追加(下着系)":
        return ("009_NSFW.yaml", "NSFW", _nsfw_group_from_name(gn))

    if cn in {"R15 ベース", "R15 グラビアツール"}:
        if cn == "R15 グラビアツール":
            if gn == "Scenetemplates":
                return ("006_背景_環境.yaml", "シーン", "屋外")
            return ("003_衣装_装飾.yaml", "衣服や装飾品", "スタイル")
        if gn.startswith("Fetish") or gn.startswith("R15") or gn in {"Tops", "Inners", "Outers", "Bottoms", "Socks", "Shoes", "Acc"}:
            return ("009_NSFW.yaml", "NSFW", _nsfw_group_from_name(gn))
        return _fashion_dest(cn, gn)

    if cn == "品質・画風":
        if gn == "Quality":
            return ("000_画像品質_技術.yaml", "クオリティ", "品質・解像度")
        return ("004_視覚効果.yaml", "画面", "芸術スタイル")

    if cn == "修飾子":
        return ("003_衣装_装飾.yaml", "衣服や装飾品", "素材")

    if cn == "キャラクター基本":
        if "hair" in g or "hairstyle" in g:
            return ("001_キャラクター.yaml", "髪パーツ", _hair_group(gn))
        if "eye" in g:
            grp = "目の形状" if "shape" in g else "目の色"
            return ("001_キャラクター.yaml", "顔パーツ", grp)
        return ("001_キャラクター.yaml", "人物", "キャラクター")

    if cn == "表情":
        return ("002_動作_表現.yaml", "表情動作", "その他表情")

    if cn == "ポーズ":
        return ("002_動作_表現.yaml", "基本動作・ポーズ", "特殊なポーズ・表現")

    if cn == "背景":
        return ("006_背景_環境.yaml", "シーン", "屋外")

    if cn == "ライティング":
        return ("004_視覚効果.yaml", "アングル・構図", "ライティング")

    if cn == "アングル":
        return ("004_視覚効果.yaml", "アングル・構図", "視点・角度")

    if cn == "構図":
        return ("004_視覚効果.yaml", "アングル・構図", "特殊な構図")

    if cn == "カメラ":
        return ("004_視覚効果.yaml", "アングル・構図", "レンズ・効果")

    if cn == "色":
        return ("004_視覚効果.yaml", "色・色彩", "基本色")

    if "追加小物" in cn:
        if gn == "Prop":
            return ("005_小物_道具.yaml", "アイテム", "その他のアイテム")
        if gn == "Headacc":
            return ("003_衣装_装飾.yaml", "衣装", "髪飾り・頭飾り")
        return ("003_衣装_装飾.yaml", "衣装", "アクセサリー・小物")

    if cn == "ガチャデータベース":
        if "composition" in g:
            return ("004_視覚効果.yaml", "アングル・構図", "特殊な構図")
        if "angle" in g:
            return ("004_視覚効果.yaml", "アングル・構図", "視点・角度")
        if "position" in g or "pose" in g:
            return ("002_動作_表現.yaml", "基本動作・ポーズ", "特殊なポーズ・表現")
        if "environment" in g or "scene" in g:
            return ("006_背景_環境.yaml", "シーン", "屋外")
        if "bondage" in g:
            return ("009_NSFW.yaml", "NSFW", "緊縛・BDSM")
        if any(k in g for k in ("adult", "fetish", "r18", "r15", "dialogue")):
            return ("009_NSFW.yaml", "NSFW", _nsfw_group_from_name(gn))
        return ("004_視覚効果.yaml", "アングル・構図", "フォーカス")

    if cn in {"コーデビルダー", "ファッションプリセット"}:
        if "poseset" in g or "pose collection" in g:
            return ("002_動作_表現.yaml", "基本動作・ポーズ", "特殊なポーズ・表現")
        if "expressionset" in g:
            return ("002_動作_表現.yaml", "表情動作", "その他表情")
        if "environmentset" in g:
            return ("006_背景_環境.yaml", "シーン", "屋外")
        if "compositionset" in g:
            return ("004_視覚効果.yaml", "アングル・構図", "特殊な構図")
        return _fashion_dest(cn, gn)

    if cn.startswith("ファッション:"):
        return _fashion_dest(cn, gn)

    return ("001_キャラクター.yaml", "人物", "キャラクター")


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
                fname, cat_name, group_name = _map_dest(cn, gn)
                target = _find_group(sections[fname], cat_name, group_name)
                if not target:
                    stats["errors"].append(f"{fname}/{cat_name}/{group_name} <- {cn}/{gn}")
                    continue
                if not dry_run:
                    target.setdefault("tags", {})[str(key)] = value
                existing[nk] = (fname, cat_name, group_name)
                stats["added"] += 1
                label = f"{fname}/{cat_name}/{group_name}"
                stats["by_target"][label] = stats["by_target"].get(label, 0) + 1

    if stats["errors"]:
        stats["errors"] = stats["errors"][:20]
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
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    print(merge(dry_run=args.dry_run))
