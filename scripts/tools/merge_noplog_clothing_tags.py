#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Merge noplog clothing tags in 003 into existing categories."""

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
_SECTION = os.path.join(_SCRIPT_DIR, "..", "group_tags", "sections", "003_衣装_装飾.yaml")

_STYLE_GROUP_HINTS = (
    "style", "fashion", "casual", "wear", "look", "outfit", "aesthetic", "chic",
    "minimalist", "retro", "vintage", "street", "sporty", "elegant", "cyberpunk",
    "punk", "grunge", "silhouette", "tone", "color", "mood", "design", "layer",
)


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


def _existing_keys(section: Dict) -> Dict[str, Tuple[str, str]]:
    out: Dict[str, Tuple[str, str]] = {}
    for cat in section.get("categories") or []:
        if (cat.get("name") or "").startswith("noplog ·"):
            continue
        cn = cat.get("name") or ""
        for grp in cat.get("groups") or []:
            gn = grp.get("name") or ""
            for k in (grp.get("tags") or {}):
                out[_tag_key(str(k))] = (cn, gn)
    return out


def _is_style_group(group_name: str) -> bool:
    gn = (group_name or "").strip().lower()
    if gn in {"-", "１．ベースプロンプト", "２．アレンジプロンプト"}:
        return False
    if any(k in gn for k in _STYLE_GROUP_HINTS):
        return True
    if re.match(r"^\d{2}s\s", gn):
        return True
    if gn in {"adorable", "alluring", "charming", "cute outfit", "sensual", "stylish", "sweet"}:
        return True
    return False


def _classify_item(tag: str) -> Optional[Tuple[str, str]]:
    t = _tag_key(tag)

    if any(k in t for k in ("shoes", "boots", "sneakers", "sandals", "slippers", "heels", "flats", "loafers", "pumps", "footwear", "mules", "espadrille", "brogues", "cleats")):
        return "衣装", "靴"
    if any(k in t for k in ("socks", "stockings", "tights", "hosiery", "legwear", "over-the-knee", "knee_socks", "thighhigh")):
        return "衣装", "靴下"
    if any(k in t for k in ("dress", "gown", "one-piece", "one_piece", "romper")) and "address" not in t:
        return "衣装", "ドレス"
    if "skirt" in t:
        return "衣装", "スカート"
    if any(k in t for k in ("pants", "jeans", "trousers", "shorts", "leggings", "joggers", "culottes", "chinos", "briefs", "boxers", "panties", "bell-bottom", "cargo_pants")):
        return "衣装", "パンツ"
    if any(k in t for k in ("bikini", "swimsuit", "swimwear", "bathing_suit")):
        return "衣装", "水着"
    if any(k in t for k in ("kimono", "yukata", "hakama", "furisode")):
        return "衣装", "和服"
    if any(k in t for k in ("coat", "jacket", "blazer", "cardigan", "hoodie", "parka", "anorak", "vest", "cape", "poncho", "bolero", "trench", "windbreaker")):
        return "衣装", "アウター"
    if any(k in t for k in ("glasses", "eyeglasses", "sunglasses", "goggles")):
        return "衣服や装飾品", "メガネ"
    if any(k in t for k in ("hat", "cap", "beanie", "beret", "headband", "turban", "balaclava", "circlet", "crown", "tiara", "headwear")):
        return "衣服や装飾品", "帽子"
    if any(k in t for k in ("hairpin", "hair_clip", "hair_ribbon", "hair_band", "hair_tie", "scrunchie", "hair_ornament", "hair_accessory")):
        return "衣装", "髪飾り・頭飾り"
    if "earring" in t:
        return "衣服や装飾品", "耳飾り"
    if any(k in t for k in ("necklace", "choker", "pendant")):
        return "衣服や装飾品", "首飾り"
    if any(k in t for k in ("bracelet", "ring", "anklet", "brooch", "jewelry", "jewellery")):
        return "衣装", "アクセサリー・小物"
    if "glove" in t or "mitten" in t:
        return "衣服や装飾品", "手袋"
    if "mask" in t and "balaclava" not in t:
        return "衣服や装飾品", "マスク"
    if any(k in t for k in ("scarf", "muffler", "stole")):
        return "衣服や装飾品", "スカーフ"
    if any(k in t for k in ("bag", "purse", "handbag", "backpack", "satchel", "clutch", "briefcase", "tote")):
        return "衣装", "アクセサリー・小物"
    if any(k in t for k in ("armor", "armour", "chainmail", "helmet", "shield", "buckler")):
        return "衣服や装飾品", "よろい"
    if any(k in t for k in ("sword", "rifle", "gun", "bow", "dagger", "lance", "staff", "weapon", "mace", "halberd", "crossbow", "spear", "nunchaku", "flail")):
        return "衣服や装飾品", "その他"
    if "maid" in t or "devil_costume" in t or "jester" in t or "zombie_costume" in t:
        return "衣装", "コスチューム・特殊衣装"
    if "nurse" in t or ("uniform" in t and "school" not in t):
        return "衣装", "制服"
    if any(k in t for k in ("pajama", "nightwear", "sleepwear", "lingerie", "bra", "bralette", "negligee", "loungewear", "nightgown")):
        return "衣装", "カジュアル・部屋着"
    if any(k in t for k in ("tie", "bowtie", "bow_tie", "ascot", "cravat")):
        return "衣服や装飾品", "襟元"
    if "belt" in t:
        return "衣服や装飾品", "腰部"
    if any(k in t for k in ("shirt", "blouse", "top", "sweater", "tee", "t-shirt", "tank", "knit", "pullover", "camisole", "bodysuit", "hoodie")):
        return "衣装", "シャツ"
    if any(k in t for k in ("stripe", "checkered", "plaid", "polka", "floral", "paisley", "pattern", "print", "geometric", "camouflage", "animal_print")):
        return "衣服や装飾品", "パターン"
    if any(k in t for k in ("cotton", "silk", "satin", "denim", "leather", "wool", "linen", "chiffon", "velvet", "lace", "knit_fabric", "corduroy", "tweed")):
        return "衣服や装飾品", "素材"
    return None


def _map_by_group(group_name: str) -> Optional[Tuple[str, str]]:
    gn = group_name or ""

    if any(k in gn for k in ("髪飾り", "🔹4．結び目")):
        return "衣装", "髪飾り・頭飾り"
    if any(k in gn for k in ("柄", "模様", "ベーシック", "伝統・スタイル", "抽象", "自然・生物", "モチーフ", "🔹1．柄")):
        return "衣服や装飾品", "パターン"
    if "素材" in gn or "🔹2．素材" in gn:
        return "衣服や装飾品", "素材"
    if any(k in gn for k in ("シルエット", "🔹3．シルエット")):
        return "衣装", "ドレス"
    if any(k in gn for k in ("デザイン /", "🔹4．デザイン", "形状・デザイン", "ディテール")):
        return "衣装", "装飾・デザイン"
    if "配色" in gn:
        return "衣装", "装飾・デザイン"
    if "靴・足元" in gn:
        return "衣装", "靴"
    if "アイウェア" in gn:
        return "衣服や装飾品", "メガネ"
    if "ヘッドウェア" in gn:
        return "衣服や装飾品", "帽子"
    if "耳飾り" in gn:
        return "衣服や装飾品", "耳飾り"
    if any(k in gn for k in ("小物・アクセサリー", "🔹6．アクセサリー")):
        return "衣装", "アクセサリー・小物"
    if "トップス" in gn:
        return "衣装", "シャツ"
    if "ボトムス" in gn:
        return "衣装", "ボトムス"
    if "ワンピース" in gn or ("ドレス" in gn and "シャツ" not in gn):
        return "衣装", "ドレス"
    if "アウター" in gn:
        return "衣装", "アウター"
    if any(k in gn for k in ("インナー", "下着")):
        return "衣装", "カジュアル・部屋着"
    if "ルームウェア" in gn:
        return "衣装", "カジュアル・部屋着"
    if "３-６" in gn:
        return None  # mixed – use tag classification
    return None


def _map_tag(tag: str, group_name: str) -> Tuple[str, str]:
    gn = group_name or ""

    if gn.strip() == "-" or _is_style_group(gn):
        return "衣服や装飾品", "スタイル"

    by_group = _map_by_group(gn)
    if by_group:
        return by_group

    by_tag = _classify_item(tag)
    if by_tag:
        return by_tag

    if any(k in gn for k in ("ベースプロンプト", "アレンジプロンプト")):
        return "衣装", "シャツ"

    if "装飾" in gn:
        return "衣服や装飾品", "装飾"

    return "衣服や装飾品", "その他"


def merge() -> Dict:
    section = _load()
    existing = _existing_keys(section)
    stats = {"added": 0, "skipped": 0, "by_target": {}}

    source_cats = [c for c in (section.get("categories") or []) if (c.get("name") or "").startswith("noplog ·")]
    if not source_cats:
        return {"error": "no noplog categories"}

    for cat in source_cats:
        for grp in cat.get("groups") or []:
            gn = grp.get("name") or ""
            for key, value in (grp.get("tags") or {}).items():
                nk = _tag_key(str(key))
                if not nk or nk in existing:
                    stats["skipped"] += int(bool(nk and nk in existing))
                    continue
                cat_name, group_name = _map_tag(str(key), gn)
                target = _find_group(section, cat_name, group_name)
                if not target:
                    raise RuntimeError(f"Missing group: {cat_name}/{group_name}")
                target.setdefault("tags", {})[str(key)] = value
                existing[nk] = (cat_name, group_name)
                stats["added"] += 1
                dest = f"{cat_name}/{group_name}"
                stats["by_target"][dest] = stats["by_target"].get(dest, 0) + 1

    section["categories"] = [c for c in (section.get("categories") or []) if not (c.get("name") or "").startswith("noplog ·")]
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
