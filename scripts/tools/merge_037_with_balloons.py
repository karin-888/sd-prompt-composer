#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Merge withballoons.jp tags from 037 into 009_NSFW."""

from __future__ import annotations

import os
import re
import sys
from typing import Dict, Optional, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
_SECTIONS_DIR = os.path.join(_SCRIPT_DIR, "..", "group_tags", "sections")

SOURCE_FILE = "037_with_balloons_stable_diffusion_withballoons_jp.yaml"
TARGET_FILE = "009_NSFW.yaml"

Dest = Tuple[str, str, str]


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


def _existing_keys(section: Dict) -> Dict[str, Dest]:
    out: Dict[str, Dest] = {}
    for cat in section.get("categories") or []:
        cn = cat.get("name") or ""
        for grp in cat.get("groups") or []:
            gn = grp.get("name") or ""
            for k in (grp.get("tags") or {}):
                out[_tag_key(str(k))] = (TARGET_FILE, cn, gn)
    return out


def _nsfw_group(cat_name: str, group_name: str, tag: str) -> str:
    gn, t = group_name or "", (tag or "").lower()

    if cat_name == "衣装":
        return "服"

    if cat_name == "シチュエーション":
        return "表情・顔"

    if cat_name != "NSFW呪文":
        return "特殊・シチュエーション"

    if gn == "Hなポーズ":
        return "動作・ポーズ"
    if gn.startswith("プレイ"):
        if re.search(r"(vibrator|dildo|inserted|masturbation|オナニー)", t):
            return "性玩具・道具" if "vibrator" in t or "dildo" in t else "動作・ポーズ"
        return "特殊・シチュエーション"
    if "＋射精" in gn or "口内射精" in gn:
        return "精液・愛液"
    if "＋挿入" in gn or "＋立SEX" in gn:
        return "性行為・体位"
    if "スマホ" in gn:
        return "スマホ写真"
    if "恥じらい" in gn or "絶望顔" in gn:
        return "表情・顔"
    if "セルフ" in gn:
        return "動作・ポーズ"
    if "2コマ" in gn:
        return "性行為・体位"

    # 状況補足* — tag hints
    if re.search(r"(fellatio|blowjob|oral|irrumatio|handjob|paizuri|titty_fuck|breasts_blowjob|licking_penis)", t):
        return "フェラ・イラマチオ・キス"
    if re.search(r"(vibrator|dildo|bullet_vibrator|onahole|バイブ|ローター|plug)", t):
        return "性玩具・道具"
    if re.search(r"(cum|facial|creampie|bukkake|projectile_cum|射精|中出し|精液|ごっくん)", t):
        return "精液・愛液"
    if re.search(r"(bondage|bdsm|shackles|torn_clothes|縛|拘束|blindfold|gag)", t):
        return "緊縛・BDSM"
    if re.search(r"(missionary|standing_sex|penis_insert|sex:1|gangbang|threesome|rape|挿入|騎乗|立sex)", t):
        return "性行為・体位"
    if re.search(r"(nipple|breast|paizuri|乳|胸)", t) and "cum" not in t:
        return "乳・乳輪・ピアス"
    if re.search(r"(ahegao|orgasm|blush|embarrassed|expression|face|顔|表情|despare|despair|cry)", t):
        return "表情・顔"
    if re.search(r"(masturbation|handbra|spread_legs|wariza|ポーズ|pose)", t):
        return "動作・ポーズ"

    return "特殊・シチュエーション"


def _map_dest(cat_name: str, group_name: str, tag: str) -> Dest:
    grp = _nsfw_group(cat_name, group_name, tag)
    return (TARGET_FILE, "NSFW", grp)


def merge(*, dry_run: bool = False) -> Dict:
    target = _load_section(TARGET_FILE)
    existing = _existing_keys(target)
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
                group = _find_group(target, cat_name, group_name)
                if not group:
                    stats["errors"].append(f"{fname}/{cat_name}/{group_name} <- {cn}/{gn}/{key}")
                    continue
                if not dry_run:
                    group.setdefault("tags", {})[str(key)] = value
                existing[nk] = (fname, cat_name, group_name)
                stats["added"] += 1
                label = f"{cat_name}/{group_name}"
                stats["by_target"][label] = stats["by_target"].get(label, 0) + 1

    if stats["errors"]:
        stats["errors"] = stats["errors"][:20]
        return stats

    if not dry_run:
        _save_section(TARGET_FILE, target)
        os.remove(os.path.join(_SECTIONS_DIR, SOURCE_FILE))
        sys.path.insert(0, _TOOLS_DIR)
        from rebuild_manifest import rebuild
        stats["manifest"] = rebuild()

    return stats


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    import json
    print(json.dumps(merge(dry_run=dry), ensure_ascii=False, indent=2))
