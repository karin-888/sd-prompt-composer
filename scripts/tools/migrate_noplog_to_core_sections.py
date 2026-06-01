#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Move tags from 009_noplog.yaml into core section files 000-008."""

from __future__ import annotations

import glob
import json
import os
import pickle
import re
import sys
from copy import deepcopy
from typing import Dict, List, Optional, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
_GROUP_TAGS = os.path.join(_SCRIPT_DIR, "..", "group_tags")
_SECTIONS = os.path.join(_GROUP_TAGS, "sections")

TARGETS = {
    "000": "000_画像品質_技術.yaml",
    "001": "001_キャラクター.yaml",
    "002": "002_動作_表現.yaml",
    "003": "003_衣装_装飾.yaml",
    "004": "004_視覚効果.yaml",
    "005": "005_小物_道具.yaml",
    "006": "006_背景_環境.yaml",
    "007": "007_食べ物.yaml",
    "008": "008_ジャンル_世界観.yaml",
}

NOPLOG_FILE = os.path.join(_SECTIONS, "009_noplog.yaml")


def _tag_key(tag: str) -> str:
    return (tag or "").strip().lower()


def _short_name(name: str, max_len: int = 48) -> str:
    s = re.sub(r"\s+", " ", (name or "").strip())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + "…"


def _load_section(path: str) -> Dict:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    return data[0] if isinstance(data, list) and data else {}


def _save_section(path: str, section: Dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump([section], f, allow_unicode=True, sort_keys=False, width=120)


def _collect_tags(section: Dict) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for cat in section.get("categories") or []:
        for grp in cat.get("groups") or []:
            for k, v in (grp.get("tags") or {}).items():
                out[_tag_key(str(k))] = str(k)
    return out


def _target_for(cat_name: str, group_name: str) -> str:
    cn = cat_name or ""
    gn = group_name or ""
    blob = f"{cn} {gn}".lower()

    # Food (rare)
    if any(k in blob for k in ["食べ物", "food", "フルーツ柄"]) and "柄" not in cn and "模様" not in cn:
        if "フルーツ" in gn and ("自然・生物" in gn or "柄" in cn):
            pass  # textile pattern, not food section
        elif re.search(r"(料理|レストラン|カフェ)", cn):
            return "007"

    # Background / scenery
    if ("背景" in cn or "風景" in cn) and "服装" not in cn and "ワンピース" not in cn and "立ち" not in cn:
        return "006"

    # Clothing / fashion / patterns / dress
    if any(k in cn for k in ["服装", "ワンピース", "柄・模様", "fashion", "衣装"]):
        return "003"

    # Colors / lighting / visual tone
    if "色彩" in cn or "色・トーン" in cn:
        return "004"
    if "ライティング" in gn or "ライティング" in cn:
        return "004"

    # Camera / composition / framing
    if any(k in cn for k in ["アングル", "構図", "表現技法"]):
        if any(k in gn for k in ["ポーズ", "表情"]):
            return "002"
        return "004"
    if any(k in gn for k in ["描写範囲", "カメラアングル", "被写体", "目線"]):
        return "004"

    # Hair (ponytail, hair color/style articles)
    if any(k in cn for k in ["ポニーテール", "髪型", "髪色"]):
        if any(k in gn for k in ["髪飾り", "装飾"]):
            return "003"
        return "001"

    # Face / body character
    if any(k in cn for k in ["理想の顔", "顔・頭", "体型", "人物設定"]):
        if any(k in gn for k in ["アクセサリー", "装飾", "ヘッドウェア", "アイウェア", "耳飾り"]):
            return "003"
        return "001"

    # Race / ethnicity
    if any(k in cn for k in ["人種", "種族"]):
        return "001"

    # Expressions
    if "表情" in cn or re.search(r"^�?[１１]?[．.]?[喜怒悲驚照不安恐嫌無動内]", gn):
        return "002"

    # Poses / standing
    if any(k in cn for k in ["ポーズ", "立ち"]):
        return "002"

    # 2400 comprehensive — group-level split
    if "2400" in cn or "完全網羅" in cn:
        if any(k in gn for k in ["描画スタイル", "表現スタイル"]):
            return "000"
        if "美術様式" in gn:
            return "008"
        if any(k in gn for k in ["人物像", "人種", "職業"]):
            return "001"
        if "表情" in gn:
            return "002"
        if "ポーズ" in gn:
            return "002"
        if "装飾" in gn:
            return "003"
        if any(k in gn for k in ["描写範囲", "カメラアングル", "被写体"]):
            return "004"
        if "ライティング" in gn:
            return "004"
        return "000"

    # Job / held items stub
    if "職業・装飾" in cn:
        if "持ち物" in gn:
            return "005"
        return "003"

    # Art / render style keywords in group names (fallback for style micro-groups)
    if any(k in gn for k in ["描画", "スタイル", "style", "painting", "sketch"]):
        return "000"

    return "001"


def _ensure_category(section: Dict, cat_name: str) -> Dict:
    for cat in section.get("categories") or []:
        if (cat.get("name") or "") == cat_name:
            return cat
    cat = {"name": cat_name, "groups": []}
    section.setdefault("categories", []).append(cat)
    return cat


def _ensure_group(cat: Dict, group_name: str) -> Dict:
    for grp in cat.get("groups") or []:
        if (grp.get("name") or "") == group_name:
            return grp
    grp = {"name": group_name, "tags": {}}
    cat.setdefault("groups", []).append(grp)
    return grp


def migrate(*, dry_run: bool = False) -> Dict:
    sys.path.insert(0, _TOOLS_DIR)
    from split_default_by_section import _collect_paths_and_index

    targets: Dict[str, Dict] = {}
    seen: Dict[str, str] = {}  # tag_key -> source file id

    for tid, fname in TARGETS.items():
        path = os.path.join(_SECTIONS, fname)
        section = _load_section(path)
        targets[tid] = section
        for k in _collect_tags(section):
            if k not in seen:
                seen[k] = tid

    with open(NOPLOG_FILE, encoding="utf-8") as f:
        noplog_data = yaml.safe_load(f) or []
    noplog = noplog_data[0] if isinstance(noplog_data, list) else {}

    stats = {
        "moved": 0,
        "skipped_dup": 0,
        "groups": 0,
        "by_target": {k: 0 for k in TARGETS},
    }

    for cat in noplog.get("categories") or []:
        cat_name = cat.get("name") or ""
        short = _short_name(cat_name)
        dest_cat_names: Dict[str, str] = {}

        for grp in cat.get("groups") or []:
            group_name = grp.get("name") or "-"
            tags: Dict = grp.get("tags") or {}
            if not tags:
                continue

            tid = _target_for(cat_name, group_name)
            if tid not in targets:
                tid = "001"

            if tid not in dest_cat_names:
                dest_cat_names[tid] = f"noplog · {short}"

            dest_section = targets[tid]
            dest_cat = _ensure_category(dest_section, dest_cat_names[tid])
            dest_grp = _ensure_group(dest_cat, group_name)

            added = 0
            for key, value in tags.items():
                nk = _tag_key(str(key))
                if not nk:
                    continue
                if nk in seen:
                    stats["skipped_dup"] += 1
                    continue
                dest_grp.setdefault("tags", {})[str(key)] = value
                seen[nk] = tid
                added += 1
                stats["moved"] += 1
                stats["by_target"][tid] += 1

            if added:
                stats["groups"] += 1

    if not dry_run:
        for tid, fname in TARGETS.items():
            _save_section(os.path.join(_SECTIONS, fname), targets[tid])

        if os.path.isfile(NOPLOG_FILE):
            os.remove(NOPLOG_FILE)

        # rebuild manifest
        files = sorted(glob.glob(os.path.join(_SECTIONS, "*.yaml")))
        manifest_sections = []
        all_paths: List[Dict] = []
        all_path_counts: Dict[str, int] = {}
        all_path_entries: List[Dict] = []
        search_index: List[Dict] = []
        seen_index = set()

        for rel_file in files:
            rel = os.path.join("sections", os.path.basename(rel_file)).replace("\\", "/")
            with open(rel_file, encoding="utf-8") as f:
                data = yaml.safe_load(f) or []
            if not data:
                continue
            section = data[0] if isinstance(data, list) else data
            paths, path_counts, path_entries, rows = _collect_paths_and_index(section)
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
            manifest_sections.append(
                {
                    "name": section.get("name") or "",
                    "file": rel,
                    "tagCount": tag_count,
                    "categoryCount": len(section.get("categories") or []),
                }
            )

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
        manifest_path = os.path.join(_GROUP_TAGS, "manifest.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        index_path = os.path.join(_GROUP_TAGS, "search-index.pkl")
        with open(index_path, "wb") as f:
            pickle.dump({"version": 2, "source_mtime": 0, "rows": search_index}, f, protocol=pickle.HIGHEST_PROTOCOL)
        stats["manifest_tags"] = len(search_index)
        stats["manifest_sections"] = len(manifest_sections)

    return stats


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    stats = migrate(dry_run=args.dry_run)
    print("Migration stats:")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
