#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Merge noplog action/expression tags in 002 into existing categories."""

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
_SECTION = os.path.join(_SCRIPT_DIR, "..", "group_tags", "sections", "002_動作_表現.yaml")


def _tag_key(tag: str) -> str:
    return (tag or "").strip().lower()


def _load() -> Dict:
    with open(_SECTION, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    return data[0] if isinstance(data, list) else {}


def _save(section: Dict) -> None:
    with open(_SECTION, "w", encoding="utf-8") as f:
        yaml.dump([section], f, allow_unicode=True, sort_keys=False, width=120)


def _find_group(section: Dict, cat_name: str, group_name: str) -> Optional[Dict]:
    for cat in section.get("categories") or []:
        if (cat.get("name") or "") != cat_name:
            continue
        for grp in cat.get("groups") or []:
            if (grp.get("name") or "") == group_name:
                return grp
    return None


def _existing_keys(section: Dict, *, skip_noplog: bool = True) -> Dict[str, Tuple[str, str]]:
    out: Dict[str, Tuple[str, str]] = {}
    for cat in section.get("categories") or []:
        cn = cat.get("name") or ""
        if skip_noplog and cn.startswith("noplog ·"):
            continue
        for grp in cat.get("groups") or []:
            gn = grp.get("name") or ""
            for k in (grp.get("tags") or {}):
                out[_tag_key(str(k))] = (cn, gn)
    return out


def _is_expression_group(group_name: str) -> bool:
    gn = group_name or ""
    if "表情" in gn:
        return True
    if re.search(r"^[１１]?[１-９０]+[．.]", gn):
        return True
    if "/" in gn and any(k in gn for k in ("喜び", "怒り", "悲しみ", "驚き", "照れ", "不安", "恐怖", "嫌悪", "無表情", "動揺", "内面")):
        return True
    return False


def _map_expression(tag: str, group_name: str) -> Tuple[str, str]:
    gn = group_name or ""
    t = _tag_key(tag)

    if "喜び" in gn:
        return "表情動作", "笑"
    if "怒り" in gn:
        return "表情動作", "怒り"
    if "悲しみ" in gn:
        return "表情動作", "泣き"
    if "嫌悪" in gn:
        return "表情動作", "軽蔑"
    if "驚き" in gn or "照れ" in gn or "不安" in gn or "恐怖" in gn or "無表情" in gn or "動揺" in gn or "内面" in gn:
        return "表情動作", "その他表情"

    if any(k in t for k in ("smile", "laugh", "grin", "chuckle", "beaming", "cheerful", "delight", "giggling", "smirk")):
        return "表情動作", "笑"
    if any(k in t for k in ("angry", "rage", "furious", "grumpy", "anger", "contort", "wrath", "irritated")):
        return "表情動作", "怒り"
    if any(k in t for k in ("cry", "tear", "sad", "sorrow", "depressed", "anguish", "devastated", "weep", "sob")):
        return "表情動作", "泣き"
    if any(k in t for k in ("disgust", "contempt", "loathing", "revulsion", "scorn")):
        return "表情動作", "軽蔑"
    if any(k in t for k in ("disappoint", "despondent")) or t == "sigh":
        return "表情動作", "不幸"
    if any(k in t for k in ("fear", "afraid", "terror", "dread", "scared", "horror")):
        return "表情動作", "その他表情"
    if any(k in t for k in ("blush", "embarrass", "shy", "awkward")):
        return "表情動作", "その他表情"
    if any(k in t for k in ("surprise", "amazed", "astonish", "shock", "startled", "dumbfound")):
        return "表情動作", "その他表情"
    if any(k in t for k in ("neutral", "blank", "deadpan", "expressionless")):
        return "表情動作", "その他表情"
    return "表情動作", "その他表情"


def _map_pose(tag: str, group_name: str) -> Tuple[str, str]:
    gn = group_name or ""
    t = _tag_key(tag)

    if any(k in gn for k in ("手・腕", "表情付け")) and "表情" not in gn.replace("表情付け", ""):
        return "基本動作・ポーズ", "手の動き・ジェスチャー"
    if any(k in gn for k in ("基本編", "ニュートラル", "立ち方", "重心", "佇まい", "アングル", "視点", "背中越")):
        if any(k in t for k in ("hand", "finger", "arm", "wave", "peace", "pocket", "skirt", "fold_arm", "greeting", "v-sign", "v_sign", "thumb")):
            return "基本動作・ポーズ", "手の動き・ジェスチャー"
        if any(k in t for k in ("leg", "knee", "feet", "foot", "weight", "hip", "stride", "step")):
            return "基本動作・ポーズ", "脚の動き・姿勢"
        if "expression" in t or "sultry" in t:
            return "表情動作", "その他表情"
        return "基本動作・ポーズ", "基本姿勢"

    if "作例集" in gn or "服装" in gn:
        if any(k in t for k in ("hand", "arm", "skirt", "peace", "wave", "fold", "pinch", "fabric", "hem", "greeting")):
            return "基本動作・ポーズ", "手の動き・ジェスチャー"
        if "expression" in t or "sultry" in t:
            return "表情動作", "その他表情"
        if any(k in t for k in ("leg", "knee", "feet", "weight", "hip", "angle", "shot")):
            return "基本動作・ポーズ", "脚の動き・姿勢"
        return "基本動作・ポーズ", "基本姿勢"

    if any(k in t for k in ("lying", "lie_", "sleep", "supine", "prone", "on_side", "curled", "flat_on_back")):
        return "基本動作・ポーズ", "座り・横たわり"
    if any(k in t for k in ("sitting", "seiza", "seated", "wariza", "yokozuwari")):
        return "基本動作・ポーズ", "座り・横たわり"
    if any(k in t for k in ("squat", "kneel", "all_fours", "crouch", "dogeza")):
        return "基本動作・ポーズ", "しゃがみ・跪き"
    if any(k in t for k in ("jump", "run", "jog", "walk", "fly", "glid", "swim", "danc", "fall", "bound", "spin")):
        return "基本動作・ポーズ", "移動・運動"
    if any(k in t for k in ("box", "martial", "karate", "kick", "punch", "fight", "jiu", "muay", "kung", "fencing", "slash")):
        return "基本動作・ポーズ", "戦闘・格闘"
    if "stance" in t and any(k in t for k in ("box", "martial", "karate", "jiu", "muay", "kung", "fight")):
        return "基本動作・ポーズ", "戦闘・格闘"
    if any(k in t for k in ("pray", "bow", "meditat", "read", "writ", "eat", "drink", "cook", "shower", "bath", "yawn", "sing")):
        return "基本動作・ポーズ", "日常動作"
    if any(k in t for k in ("hand", "finger", "arm", "fist", "thumb", "peace", "wave", "pocket", "cheek", "head", "reach", "gesture", "salute", "point")):
        return "基本動作・ポーズ", "手の動き・ジェスチャー"
    if any(k in t for k in ("leg", "feet", "foot", "knee", "toe", "spread_leg", "legs_")):
        return "基本動作・ポーズ", "脚の動き・姿勢"
    if any(k in t for k in ("hug", "kiss", "embrace", "carry", "cuddle", "lap_pillow")):
        return "基本動作・ポーズ", "身体接触・親密な動作"
    if any(k in t for k in ("pose", "posture", "stand", "stance", "lean", "contrapposto")):
        return "基本動作・ポーズ", "基本姿勢"

    return "基本動作・ポーズ", "特殊なポーズ・表現"


def _map_tag(tag: str, group_name: str) -> Tuple[str, str]:
    if _is_expression_group(group_name):
        return _map_expression(tag, group_name)
    return _map_pose(tag, group_name)


def merge() -> Dict:
    section = _load()
    existing = _existing_keys(section)
    stats = {"added": 0, "skipped": 0, "by_target": {}}

    source_cats = [
        c for c in (section.get("categories") or [])
        if (c.get("name") or "").startswith("noplog ·")
    ]
    if not source_cats:
        return {"error": "no noplog categories found"}

    for cat in source_cats:
        for grp in cat.get("groups") or []:
            gn = grp.get("name") or ""
            for key, value in (grp.get("tags") or {}).items():
                nk = _tag_key(str(key))
                if not nk:
                    continue
                if nk in existing:
                    stats["skipped"] += 1
                    continue
                cat_name, group_name = _map_tag(str(key), gn)
                target = _find_group(section, cat_name, group_name)
                if not target:
                    raise RuntimeError(f"Missing group: {cat_name} / {group_name}")
                target.setdefault("tags", {})[str(key)] = value
                existing[nk] = (cat_name, group_name)
                stats["added"] += 1
                dest = f"{cat_name}/{group_name}"
                stats["by_target"][dest] = stats["by_target"].get(dest, 0) + 1

    section["categories"] = [
        c for c in (section.get("categories") or [])
        if not (c.get("name") or "").startswith("noplog ·")
    ]

    _save(section)

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
