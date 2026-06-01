#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Merge sorenuts tags from 034 into core sections 000-009."""

from __future__ import annotations

import os
import re
import sys
from typing import Dict, List, Optional, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
_SECTIONS_DIR = os.path.join(_SCRIPT_DIR, "..", "group_tags", "sections")

SOURCE_FILE = "034_sorenuts.yaml"

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

NOIR_RACE_TAGS = {
    "african-american", "caucasian", "eastern_european", "greek",
    "hispanic", "mediterranean", "middle_eastern",
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


def _char_dest(group_name: str, tag: str) -> Dest:
    gn, t = group_name or "", (tag or "").lower()
    if "ノワール" in gn and t in NOIR_RACE_TAGS:
        return ("001_キャラクター.yaml", "人物像", "人種")
    if gn == "ファンタジー (Fantasy)":
        return ("008_ジャンル_世界観.yaml", "ファンタジー", "亜人・種族")
    if re.search(r"(elf|fairy|faerie|dragonkin|golem|mutant|replicant|automaton|vampire|spirit|nymph|witch|banshee|ghoul|phantom|poltergeist|skinwalker|dwarf|fairy)", t):
        return ("008_ジャンル_世界観.yaml", "ファンタジー", "亜人・種族")
    if any(k in gn for k in ("神話", "ヴァンパイア", "ホラー", "武侠", "異世界")):
        if re.search(r"(dragon|elf|fairy|spirit|ghost|phantom|vampire|banshee|ghoul|demon|angel|beast|golem|kin)", t):
            return ("008_ジャンル_世界観.yaml", "ファンタジー", "亜人・種族")
    return ("001_キャラクター.yaml", "人物像", "職業")


def _pose_dest(group_name: str, tag: str) -> Dest:
    gn, t = group_name or "", (tag or "").lower()
    if any(k in gn for k in ("体の特徴", "ケモノ")):
        return ("001_キャラクター.yaml", "人物", "体型")
    if any(k in gn for k in ("ポーズ", "アクションポーズ", "指差し", "支持", "休息")):
        if any(k in t for k in ("hand", "finger", "arm", "leg", "sitting", "standing")):
            return ("002_動作_表現.yaml", "基本動作・ポーズ", "手の動き・ジェスチャー")
        return ("002_動作_表現.yaml", "基本動作・ポーズ", "特殊なポーズ・表現")
    return ("002_動作_表現.yaml", "基本動作・ポーズ", "日常動作" if "sitting" in t else "特殊なポーズ・表現")


def _action_dest(group_name: str, tag: str) -> Dest:
    gn, t = group_name or "", (tag or "").lower()
    if "身体活動" in gn or "Physical Activity" in gn:
        return ("002_動作_表現.yaml", "基本動作・ポーズ", "移動・運動")
    if "感情・社会" in gn or "Emo & Social" in gn:
        if re.search(r"(hug|kiss|embrace|hold_hands|touch|cuddle)", t):
            return ("002_動作_表現.yaml", "基本動作・ポーズ", "身体接触・親密な動作")
        return ("002_動作_表現.yaml", "基本動作・ポーズ", "日常動作")
    if "ファンタジー" in gn and re.search(r"(fight|attack|cast|spell|magic_combat)", t):
        return ("002_動作_表現.yaml", "基本動作・ポーズ", "戦闘・格闘")
    if re.search(r"(fight|punch|kick|attack|battle|combat|wrestl)", t):
        return ("002_動作_表現.yaml", "基本動作・ポーズ", "戦闘・格闘")
    if re.search(r"(run|walk|jump|swim|danc|climb|stretch)", t):
        return ("002_動作_表現.yaml", "基本動作・ポーズ", "移動・運動")
    return ("002_動作_表現.yaml", "基本動作・ポーズ", "日常動作")


def _cloth_dest(group_name: str, tag: str) -> Dest:
    gn = group_name or ""
    if any(k in gn for k in ("帽子", "ヘアアクセ", "フード", "パーカー")):
        if "帽子" in gn or "ヘア" in gn:
            return ("003_衣装_装飾.yaml", "衣服や装飾品", "帽子")
        return ("003_衣装_装飾.yaml", "衣装", "シャツ")
    if any(k in gn for k in ("ジュエリー", "アクセサリー")):
        return ("003_衣装_装飾.yaml", "衣装", "アクセサリー・小物")
    if "柄" in gn or "デザイン" in gn or "色タグ" in gn:
        return ("003_衣装_装飾.yaml", "衣装", "装飾・デザイン")
    if "スカート" in gn:
        return ("003_衣装_装飾.yaml", "衣装", "スカート")
    if any(k in gn for k in ("ズボン", "ショーツ")):
        return ("003_衣装_装飾.yaml", "衣装", "ボトムス")
    if any(k in gn for k in ("ワンピース", "ドレス")):
        return ("003_衣装_装飾.yaml", "衣装", "ドレス")
    if any(k in gn for k in ("ケープ", "マント", "アウター", "ベスト", "カーディガン")):
        return ("003_衣装_装飾.yaml", "衣装", "コート")
    if any(k in gn for k in ("ふんどし", "腰布")):
        return ("003_衣装_装飾.yaml", "衣装", "和服")
    if "ネックウェア" in gn or "手袋" in gn or "バッグ" in gn:
        return ("003_衣装_装飾.yaml", "衣装", "手袋・アクセサリー")
    return ("003_衣装_装飾.yaml", "衣装", "シャツ")


def _bg_dest(group_name: str, tag: str) -> Dest:
    gn = group_name or ""
    if "小物" in gn and "環境" not in gn:
        return ("005_小物_道具.yaml", "アイテム", "その他のアイテム")
    if "家具" in gn or "机" in gn:
        return ("006_背景_環境.yaml", "シーン", "家具")
    if "学校" in gn:
        return ("006_背景_環境.yaml", "シーン", "屋内")
    if "交通" in gn:
        return ("006_背景_環境.yaml", "シーン", "都市")
    if "店舗" in gn:
        return ("006_背景_環境.yaml", "シーン", "屋内")
    if "水関連" in gn:
        return ("006_背景_環境.yaml", "環境", "水")
    if "電子機器" in gn:
        return ("005_小物_道具.yaml", "デジタル機器", "デジタル機器")
    if "天候" in gn or "空" in gn:
        return ("006_背景_環境.yaml", "背景", "天候・時間帯")
    if "効果" in gn or "色・柄" in gn:
        return ("006_背景_環境.yaml", "背景", "背景色・効果")
    if "屋内" in gn:
        return ("006_背景_環境.yaml", "シーン", "屋内")
    if "屋外" in gn:
        return ("006_背景_環境.yaml", "シーン", "屋外")
    if "自然" in gn:
        return ("006_背景_環境.yaml", "植物・自然", "植物")
    if "人工" in gn:
        return ("006_背景_環境.yaml", "背景", "都市・建物")
    if "架空" in gn:
        return ("006_背景_環境.yaml", "背景", "特殊・エフェクト")
    if "e621" in gn and "小物" in gn:
        return ("005_小物_道具.yaml", "アイテム", "その他のアイテム")
    if "e621" in gn:
        return ("006_背景_環境.yaml", "シーン", "屋外")
    return ("006_背景_環境.yaml", "シーン", "屋外")


def _map_dest(cat_name: str, group_name: str, tag: str) -> Dest:
    cn = cat_name or ""
    if "画風" in cn:
        if re.search(r"(low_quality|crude_quality|substandard)", tag, re.I):
            return ("000_画像品質_技術.yaml", "ネガティブ", "画像品質")
        return ("004_視覚効果.yaml", "画面", "芸術スタイル")
    if "職業・種族" in cn or ("キャラクター" in cn and "職業" in cn):
        return _char_dest(group_name, tag)
    if "ポーズ・体" in cn:
        return _pose_dest(group_name, tag)
    if "動作・行動" in cn:
        return _action_dest(group_name, tag)
    if "服装" in cn:
        return _cloth_dest(group_name, tag)
    if "環境・背景" in cn:
        return _bg_dest(group_name, tag)
    if "表情" in cn:
        return ("002_動作_表現.yaml", "表情動作", "その他表情")
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
                fname, cat_name, group_name = _map_dest(cn, gn, str(key))
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
    import json
    print(json.dumps(merge(dry_run=dry), ensure_ascii=False, indent=2))
