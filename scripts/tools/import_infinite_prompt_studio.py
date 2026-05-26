#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Import INFINITE PROMPT STUDIO desktop-app data .js files into YAML.

The .js files all assign curated prompt dictionaries to ``window.DATA_*`` (and
similar globals). Each leaf entry is either:

- ``{l: "日本語", t: "english prompt"}`` (simple tag pair), or
- ``{l: "日本語", top: "...", outer: "...", bottom: "...", ...}``
  (composite outfit/scene preset — concatenate all non-color string fields
  into a single comma-separated prompt).

This script:
1. Runs Node.js to evaluate every ``.js`` file in the IPS data folder and
   dumps the merged ``window`` object as JSON (see ``_ips_extract.js``).
2. Walks the JSON tree and converts every leaf into a ``(category, group,
   english_tag, japanese_label)`` record.
3. Emits ``group_tags/infinite_prompt_studio.yaml``.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
for _p in (_SCRIPT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

IPS_DATA_DIR = (
    "/Users/hiori222/Downloads/INFINITE_PROMPT_STUDIO_PRODUCT_v1_1_DESKTOP_APP/"
    "resources/app/app/data"
)
SECTION_NAME = "INFINITE PROMPT STUDIO"

# Top-level window keys that should not be treated as tag dictionaries.
SKIP_TOP_KEYS = {
    # config-style entries (samplers, upscalers, controlnet lists)
    "CONFIG_PRESETS",
    "CONTROLNET_MODEL_LIST",
    "CONTROLNET_MODULE_LIST",
    # already covered exhaustively by the existing danbooru.yaml import
    "DANBOORU_TAG_COMPLETE",
    # internal flags / sentinel values
    "OUTFIT_BUILDER_QUALITY_EXPANSION_LOADED",
}

# Fields ending with these suffixes are color hints; skip when composing
# composite presets (they store color names, not prompt fragments).
COLOR_HINT_SUFFIXES = ("C",)

# Reasonable human-readable category labels for major top-level objects.
CATEGORY_LABELS = {
    "DATA_R18": "R18 ベース",
    "ADULT_R18_EXPANSION": "R18 拡張",
    "R18_CGSET_TOOLS": "R18 CGセットツール",
    "DATA_COLORS": "色",
    "DATA_ANGLES": "アングル",
    "DATA_BACKGROUNDS": "背景",
    "DATA_CAMERA": "カメラ",
    "DATA_CHARACTER": "キャラクター基本",
    "DATA_COMPOSITIONS": "構図",
    "DATA_EXPRESSIONS": "表情",
    "DATA_LIGHTING": "ライティング",
    "DATA_MODIFIERS": "修飾子",
    "DATA_POSES": "ポーズ",
    "DATA_COMMON": "共通タグ",
    "DATA_BAND": "ファッション: バンド",
    "DATA_GYARU": "ファッション: ギャル",
    "DATA_MIKO": "ファッション: 巫女",
    "DATA_SCHOOL": "ファッション: 制服",
    "DATA_MAID": "ファッション: メイド",
    "DATA_RPG": "ファッション: RPG",
    "DATA_CASUAL": "ファッション: カジュアル",
    "DATA_NURSE": "ファッション: ナース",
    "DATA_NUN": "ファッション: シスター",
    "DATA_DRESS": "ファッション: ドレス",
    "DATA_GOTH": "ファッション: ゴス",
    "DATA_IDOL": "ファッション: アイドル",
    "DATA_WAFUKU": "ファッション: 和服",
    "DATA_OL": "ファッション: OL",
    "DATA_PRINCESS": "ファッション: お姫様",
    "DATA_JIRAI": "ファッション: 地雷系",
    "DATA_SHIBUYA": "ファッション: 渋谷系",
    "DATA_BUNNY": "ファッション: バニー",
    "DATA_CHINA": "ファッション: チャイナ",
    "DATA_DATECASUAL": "ファッション: デートカジュアル",
    "DATA_DOWNER": "ファッション: ダウナー系",
    "FASHION_PRESETS": "ファッションプリセット",
    "FASHION_INFINITE_GACHA": "ファッション無限ガチャ",
    "OUTFIT_COORD_BUILDER": "コーデビルダー",
    "GENRE_DOWNER_EXTRA": "ダウナー系 (追加小物)",
    "DATA_EXTRA_COMMON": "共通追加(下着系)",
    "DATA_SWIMSUIT": "ファッション: 水着",
    "DATA_COSPLAY": "ファッション: コスプレ",
    "DATA_OCCUPATION": "ファッション: 職業系",
    "DATA_MAGICALGIRL": "ファッション: 魔法少女",
    "DATA_MECHA": "ファッション: メカ",
    "DATA_MILITARY": "ファッション: ミリタリー",
    "DATA_NINJA": "ファッション: 忍者",
    "GENRE_NINJA_EXTRA": "忍者 (追加小物)",
    "DATA_PAJAMA": "ファッション: パジャマ",
    "DATA_R15": "R15 ベース",
    "DATA_RACEQUEEN": "ファッション: レースクイーン",
    "DATA_ROOMWEAR": "ファッション: 部屋着",
    "DATA_SAMURAI": "ファッション: 侍",
    "GENRE_SAMURAI_EXTRA": "侍 (追加小物)",
    "DATA_VTUBER": "ファッション: VTuber",
    "GENRE_VTUBER_EXTRA": "VTuber (追加小物)",
    "GACHA_DATABASE": "ガチャデータベース",
    "DATA_QUALITY": "品質・画風",
    "R15_GRAVURE_TOOLS": "R15 グラビアツール",
}


def run_node_extractor(data_dir: str) -> Dict:
    """Run the Node.js helper and return the parsed JSON dump."""
    extractor = os.path.join(_TOOLS_DIR, "_ips_extract.js")
    files = sorted(
        os.path.join(data_dir, f)
        for f in os.listdir(data_dir)
        if f.endswith(".js")
    )
    print(f"[ips] node-evaluating {len(files)} files…")
    proc = subprocess.run(
        ["node", extractor, *files],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        print("[ips] node stderr:", proc.stderr)
        raise SystemExit(proc.returncode)
    if proc.stderr.strip():
        print("[ips] node warnings:", proc.stderr.strip())
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# Leaf-entry conversion ------------------------------------------------------


_BLOCKLIST_VAL = {"none", "なし", ""}


def _clean_en(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = text.strip().strip(",")
    text = re.sub(r"\s+", " ", text)
    return text


def _clean_jp(text: str) -> str:
    if not isinstance(text, str):
        return ""
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    text = text.strip("：:、,.;★◆●▼▶✔ ")
    return text


def _useful_en(text: str) -> bool:
    if not text or len(text) > 400:
        return False
    if text.lower() in _BLOCKLIST_VAL:
        return False
    if not re.search(r"[a-zA-Z]", text):
        return False
    return True


def _useful_jp(text: str) -> bool:
    if not text or len(text) > 100:
        return False
    if text.lower() in _BLOCKLIST_VAL:
        return False
    return True


def _is_color_field(key: str) -> bool:
    return any(key.endswith(s) for s in COLOR_HINT_SUFFIXES) and key != "c"


def _compose_english(obj: Dict) -> str:
    """For composite ``{l, top, outer, ...}`` objects, concatenate string fields."""
    parts: List[str] = []
    for k, v in obj.items():
        if k in ("l", "label", "cat", "category", "c"):
            continue
        if _is_color_field(k):
            continue
        if not isinstance(v, str):
            continue
        v_clean = _clean_en(v)
        if not v_clean or v_clean.lower() in _BLOCKLIST_VAL:
            continue
        parts.append(v_clean)
    return ", ".join(parts)


def _entry_to_pair(obj: Dict) -> Optional[Tuple[str, str]]:
    """Convert one ``{l: ..., t: ...}`` (or composite) object to ``(en, jp)``."""
    if not isinstance(obj, dict):
        return None
    jp = _clean_jp(obj.get("l", "") or obj.get("label", ""))
    if not _useful_jp(jp):
        return None
    # simple form
    if "t" in obj and isinstance(obj["t"], str):
        en = _clean_en(obj["t"])
        if _useful_en(en):
            return en, jp
    # composite form
    en = _compose_english(obj)
    if _useful_en(en):
        return en, jp
    return None


# ---------------------------------------------------------------------------
# Tree walking ---------------------------------------------------------------


def _humanize(name: str) -> str:
    n = name.replace("_", " ")
    n = re.sub(r"\bDATA\s*", "", n)
    return n.strip().capitalize() if n else name


def _looks_like_leaf_list(arr: List) -> bool:
    return bool(arr) and isinstance(arr[0], dict) and ("l" in arr[0] or "label" in arr[0])


def _walk(node, path: List[str], out_groups: Dict[str, Dict[str, str]]) -> None:
    """Recursively walk the IPS data tree and collect (group, en, jp) leaves.

    The current ``path`` becomes the group name (joined with " / ").
    """
    if isinstance(node, list):
        if _looks_like_leaf_list(node):
            group_name = " / ".join(path) if path else "default"
            tags = out_groups.setdefault(group_name, {})
            for obj in node:
                pair = _entry_to_pair(obj) if isinstance(obj, dict) else None
                if not pair:
                    continue
                en, jp = pair
                tags.setdefault(en, jp)
        else:
            # Some lists nest deeper (e.g. arrays of arrays). Iterate.
            for i, item in enumerate(node):
                _walk(item, path + [str(i)] if not isinstance(item, dict) else path, out_groups)
        return
    if isinstance(node, dict):
        # Direct leaf?
        if "l" in node and ("t" in node or any(isinstance(v, str) for k, v in node.items() if k != "l")):
            # treat the dict itself as a single leaf, parented by current path
            pair = _entry_to_pair(node)
            if pair:
                group_name = " / ".join(path) if path else "default"
                en, jp = pair
                out_groups.setdefault(group_name, {}).setdefault(en, jp)
            return
        for k, v in node.items():
            _walk(v, path + [_humanize(k)], out_groups)


def extract_tags(win: Dict) -> Dict[str, Dict[str, Dict[str, str]]]:
    """Return ``{category_label: {group_name: {english_tag: japanese}}}``."""
    out: Dict[str, Dict[str, Dict[str, str]]] = {}
    for top_key, value in win.items():
        if top_key in SKIP_TOP_KEYS:
            continue
        groups: Dict[str, Dict[str, str]] = {}
        _walk(value, [], groups)
        # drop empty groups
        groups = {g: tags for g, tags in groups.items() if tags}
        if not groups:
            continue
        cat_label = CATEGORY_LABELS.get(top_key, _humanize(top_key))
        # If a category already exists (eg same key written by two .js files),
        # merge — keep first occurrence's Japanese, but extend new tags.
        bucket = out.setdefault(cat_label, {})
        for g, tags in groups.items():
            target = bucket.setdefault(g, {})
            for en, jp in tags.items():
                target.setdefault(en, jp)
    return out


# ---------------------------------------------------------------------------
# YAML output ----------------------------------------------------------------


def build_yaml(per_cat: Dict[str, Dict[str, Dict[str, str]]]) -> List[Dict]:
    section = {"name": SECTION_NAME, "categories": []}
    for cat_label, groups in per_cat.items():
        cat_obj = {"name": cat_label, "groups": []}
        for group_name, tags in groups.items():
            if not tags:
                continue
            cat_obj["groups"].append(
                {
                    "name": group_name,
                    "tags": dict(sorted(tags.items(), key=lambda kv: kv[0].lower())),
                }
            )
        if cat_obj["groups"]:
            section["categories"].append(cat_obj)
    return [section]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=IPS_DATA_DIR)
    parser.add_argument(
        "--out",
        default=os.path.join(_SCRIPT_DIR, "..", "group_tags", "infinite_prompt_studio.yaml"),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    blob = run_node_extractor(args.data_dir)
    win = blob.get("window", {})
    per_cat = extract_tags(win)

    grand = sum(len(t) for groups in per_cat.values() for t in groups.values())
    print(f"[ips] categories={len(per_cat)} total_tags={grand}")
    for cat, groups in per_cat.items():
        n = sum(len(t) for t in groups.values())
        print(f"  {cat}: {len(groups)} groups, {n} tags")

    if args.dry_run:
        print("[dry-run] not writing YAML")
        return

    data = build_yaml(per_cat)
    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            data,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=200,
        )
    print(f"[ips] wrote: {out_path}")


if __name__ == "__main__":
    main()
