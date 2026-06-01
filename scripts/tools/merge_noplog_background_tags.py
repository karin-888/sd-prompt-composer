#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Merge noplog background tags in 006 into existing categories/groups."""

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
_SECTION = os.path.join(_SCRIPT_DIR, "..", "group_tags", "sections", "006_背景_環境.yaml")
_NOPLOG_CAT_PREFIX = "noplog · Stable Diffusion 背景/風景"
_BAK = os.path.join(_SCRIPT_DIR, "..", "group_tags", "default.yaml.bak")


def _load_noplog_source_groups() -> List[Dict]:
    """Recover the 4 background groups from default.yaml.bak."""
    with open(_BAK, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    for sec in data:
        if (sec.get("name") or "") != "noplog":
            continue
        for cat in sec.get("categories") or []:
            if "背景/風景" in (cat.get("name") or ""):
                return list(cat.get("groups") or [])
    raise RuntimeError("noplog background groups not found in default.yaml.bak")


def _tag_key(tag: str) -> str:
    return (tag or "").strip().lower()


def _load() -> Dict:
    with open(_SECTION, encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    return data[0] if isinstance(data, list) else {}


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
        cn = cat.get("name") or ""
        for grp in cat.get("groups") or []:
            gn = grp.get("name") or ""
            for k in (grp.get("tags") or {}):
                out[_tag_key(str(k))] = (cn, gn)
    return out


def _map_tag(tag: str, group_name: str) -> Tuple[str, str]:
    t = _tag_key(tag)
    g = group_name or ""

    if g.startswith("１．日常"):
        if t.startswith("in_the_") or t in {
            "indoors", "inside_a_room", "inside_the_house", "inside_the_station",
        }:
            return "背景", "室内・施設"
        if t in {"on_the_bed", "on_the_couch"}:
            return "背景", "室内・施設"
        if t in {"on_the_bus", "on_the_train", "on_the_platform", "in_the_car"}:
            return "シーン", "屋外"
        return "背景", "都市・建物"

    if g.startswith("２．場所"):
        outdoor_landmarks = (
            "castle", "tower", "shrine", "temple", "cathedral", "pyramid", "landmark",
            "colosseum", "stonehenge", "machu", "petra", "pompeii", "acropolis",
            "parthenon", "mont_", "neuschwanstein", "himeji", "fushimi", "itsukushima",
            "kinkaku", "kiyomizu", "nikko", "sagrada", "notre-dame", "versailles",
            "big_ben", "eiffel", "taj_mahal", "statue_of", "giza", "grand_canyon",
            "niagara", "angkor", "byodo", "shuri", "pagoda", "lighthouse", "windmill",
            "water_wheel", "megalith", "mausoleum", "fortress", "citadel", "rampart",
            "moat", "drawbridge", "steel_bridge", "suspension_bridge", "canal", "marina",
            "archaeological", "megalith", "tomb", "cemetery", "abbey", "monastery",
            "shrine", "itsukushima", "exterior", "facade", "basilica",
        )
        if any(x in t for x in outdoor_landmarks):
            return "シーン", "屋外"
        if "garden" in t or t in {"gazebo", "courtyard", "public_park", "zoological_garden", "roof_garden"}:
            return "シーン", "屋外"
        if "cityscape" in t or t in {"tokyo", "paris", "kyoto_scenery", "in_kyoto", "japan_landscape", "hawaii_landscape"}:
            return "背景", "都市・建物"
        if t in {"on_the_balcony", "on_the_rooftop", "on_the_terrace", "on_the_veranda"}:
            return "背景", "室内・施設"
        indoor_facility = (
            "bedroom", "office", "lobby", "basement", "staircase", "hospital", "laboratory",
            "hotel", "prison", "warehouse", "gym", "mall", "pharmacy", "college", "factory",
            "department_store", "bookstore", "music_room", "wine_cellar", "ryokan", "clinic",
            "recording_studio", "karaoke", "sauna", "hot_tub", "game_room", "billiard",
            "indoor_pool", "indoor_playground", "ice_skating", "dance_studio", "entrance",
            "police_station", "fire_station", "school_gym", "underground_mall", "shopping",
            "hospital_bedroom", "modern_office", "art_museum", "concert_hall", "live_stage",
            "movie_theatre", "party_venue", "flea_market", "great_outdoors",
        )
        if t.startswith("in_the_") or t.startswith("at_the_"):
            if any(x in t for x in indoor_facility):
                return "背景", "室内・施設"
            return "シーン", "屋外"
        if any(x in t for x in ("stadium", "court", "field", "resort", "course", "bridge")):
            return "シーン", "屋外"
        if t in {"gas_station", "car_park", "construction_site", "ski_resort", "hot_spring"}:
            return "シーン", "屋外"
        return "シーン", "屋外"

    if g.startswith("３．自然"):
        if any(x in t for x in (
            "rain", "snow", "storm", "fog", "cloud", "hurricane", "tornado", "thunder",
            "blizzard", "haze", "windy", "sunny", "weather", "fine_weather", "good_weather",
        )) or t.endswith("_scenery"):
            return "背景", "天候・時間帯"
        if any(x in t for x in (
            "spring_", "summer_", "autumn_", "winter_", "morning_", "evening_", "dawn_",
            "dusk_", "noon_", "midnight_", "early_morning", "blue_hour", "golden_hour",
        )):
            return "背景", "天候・時間帯"
        if any(x in t for x in (
            "eclipse", "mars", "jupiter", "saturn", "uranus", "venus", "earth", "comet",
            "nebula", "galaxy", "black_hole", "wormhole", "milky_way", "aurora",
            "northern_lights", "distant_galaxy",
        )):
            return "背景", "空・宇宙"
        if "_field" in t or t in {
            "orchard", "vineyard", "pasture", "ranch", "rice_field", "palm_grove",
        }:
            return "植物・自然", "植物"
        return "背景", "自然"

    if g.startswith("４．ライブラリ"):
        urban_kw = (
            "cityscape", "city", "street", "urban", "metropolis", "suburbs", "townscape",
            "streetscape", "neon", "cyberpunk", "steampunk", "dystopia", "post-apocalyptic",
            "futuristic", "deserted_city", "flooded_city", "floating_city", "ghost_town",
            "building", "architecture", "square", "district", "asphalt", "shopping",
            "cobblestone", "nightscape", "skyline", "moon_base", "space_colonies",
        )
        if any(x in t for x in urban_kw):
            return "背景", "都市・建物"
        fantasy_kw = (
            "fantasy", "magical", "enchanted", "alternate_dimension", "eden", "alien",
            "terraform", "realm", "world",
        )
        if any(x in t for x in fantasy_kw):
            return "シーン", "屋外"
        return "背景", "自然"

    return "背景", "自然"


def merge() -> Dict:
    section = _load()
    existing = _existing_keys(section)
    stats = {"added": 0, "skipped": 0, "removed_cat": False, "by_target": {}}

    source_groups = _load_noplog_source_groups()

    # Also remove stale noplog category if still present
    section["categories"] = [
        c for c in (section.get("categories") or [])
        if not (c.get("name") or "").startswith(_NOPLOG_CAT_PREFIX)
    ]

    for grp in source_groups:
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
                raise RuntimeError(f"Missing target group: {cat_name} / {group_name}")
            target.setdefault("tags", {})[str(key)] = value
            existing[nk] = (cat_name, group_name)
            stats["added"] += 1
            dest = f"{cat_name}/{group_name}"
            stats["by_target"][dest] = stats["by_target"].get(dest, 0) + 1

    stats["removed_cat"] = True

    with open(_SECTION, "w", encoding="utf-8") as f:
        yaml.dump([section], f, allow_unicode=True, sort_keys=False, width=120)

    # rebuild manifest
    sys.path.insert(0, _TOOLS_DIR)
    from split_default_by_section import _collect_paths_and_index

    group_tags_dir = os.path.join(_SCRIPT_DIR, "..", "group_tags")
    sections_dir = os.path.join(group_tags_dir, "sections")
    files = sorted(glob.glob(os.path.join(sections_dir, "*.yaml")))
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
