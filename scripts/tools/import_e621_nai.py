#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Build an e621 + NovelAI/Illustrious quality tag dictionary YAML.

- ``e621.csv`` from DominikDoom/a1111-sd-webui-tagcomplete (tag, type, count, aliases).
- Plus a hand-curated NovelAI v3 / Illustrious quality & rating token list with JP labels.

e621 tag types::

    0=general, 1=artist, 3=copyright, 4=character, 5=species, 6=invalid, 7=meta, 8=lore
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import urllib.request
from typing import Dict, List, Optional, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
for _p in (_SCRIPT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

USER_AGENT = "PromptComposerImporter/1.0 (personal local import)"
E621_CSV_URL = "https://raw.githubusercontent.com/DominikDoom/a1111-sd-webui-tagcomplete/main/tags/e621.csv"
JP_HAND_URL = "https://raw.githubusercontent.com/boorutan/booru-japanese-tag/main/danbooru-jp.csv"
JP_MACHINE_URL = "https://raw.githubusercontent.com/boorutan/booru-japanese-tag/main/danbooru-machine-jp.csv"
CACHE_DIR = "/tmp/pc-tag-import"

E621_TAG_TYPES = {
    0: "general",
    1: "artist",
    3: "copyright",
    4: "character",
    5: "species",
    6: "invalid",
    7: "meta",
    8: "lore",
}


def fetch(url: str, dest: str, force: bool = False) -> str:
    if not force and os.path.isfile(dest) and os.path.getsize(dest) > 0:
        return dest
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = resp.read()
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def load_translations(path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 2:
                continue
            tag, jp = row[0].strip(), row[1].strip()
            if tag and jp:
                out[tag] = jp
    return out


def load_e621(path: str) -> List[Tuple[str, int, int, str]]:
    rows: List[Tuple[str, int, int, str]] = []
    with open(path, encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row:
                continue
            try:
                tag = row[0].strip()
                typ = int(row[1])
                cnt = int(row[2])
            except (IndexError, ValueError):
                continue
            if not tag:
                continue
            rows.append((tag, typ, cnt, row[3] if len(row) > 3 else ""))
    return rows


# Curated JP labels for common e621 species/meta tags.
E621_JP_HINTS: Dict[str, str] = {
    # species / form
    "anthro": "アンスロ（人型動物）",
    "feral": "フェラル（四足獣型）",
    "humanoid": "ヒューマノイド",
    "mammal": "哺乳類",
    "canine": "犬科",
    "feline": "猫科",
    "wolf": "オオカミ",
    "fox": "キツネ",
    "cat": "ネコ",
    "dog": "イヌ",
    "rabbit": "ウサギ",
    "deer": "シカ",
    "horse": "ウマ",
    "dragon": "ドラゴン",
    "scalie": "爬虫類系",
    "reptile": "爬虫類",
    "avian": "鳥類",
    "bird": "鳥",
    "shark": "サメ",
    "fish": "魚",
    "mouse": "ネズミ",
    "raccoon": "アライグマ",
    "bear": "クマ",
    "monkey": "サル",
    "primate": "霊長類",
    "kemono": "ケモノ",
    "kemonomimi": "ケモミミ",
    "ungulate": "蹄動物",
    "rodent": "齧歯類",
    # anthro body parts
    "muzzle": "鼻先（マズル）",
    "snout": "鼻面",
    "fur": "毛皮",
    "paws": "肉球付きの手足",
    "pawpads": "肉球",
    "tail": "尻尾",
    "ears": "耳",
    "claws": "爪",
    "fangs": "牙",
    "tongue_out": "舌出し",
    "wings": "翼",
    "horns": "角",
    # composition / meta
    "absurd_res": "超高解像度",
    "hi_res": "高解像度",
    "detailed_background": "詳細な背景",
    "simple_background": "シンプルな背景",
    "transparent_background": "透明背景",
    "white_background": "白背景",
}


def count_tier_general(count: int) -> Optional[str]:
    if count >= 10000:
        return "★★★ 超頻出 (10K+)"
    if count >= 1000:
        return "★★ 頻出 (1K-10K)"
    if count >= 500:
        return "★ 標準 (500-1K)"
    return None


def count_tier_species(count: int) -> Optional[str]:
    if count >= 5000:
        return "★★★ 主要種 (5K+)"
    if count >= 1000:
        return "★★ 一般種 (1K-5K)"
    if count >= 500:
        return "★ その他種 (500-1K)"
    return None


def count_tier_meta(count: int) -> Optional[str]:
    if count >= 1000:
        return "★★ 主要 (1K+)"
    if count >= 100:
        return "★ 一般 (100-1K)"
    return None


TIER_FUNCS = {
    "general": count_tier_general,
    "species": count_tier_species,
    "meta": count_tier_meta,
}

CATEGORY_LABELS = {
    "general": "一般タグ",
    "species": "種族・形態",
    "meta": "メタタグ（構図・解像度）",
}


def build_e621_yaml_section(
    rows: List[Tuple[str, int, int, str]],
    jp_hand: Dict[str, str],
    jp_machine: Dict[str, str],
) -> Dict:
    categories: Dict[str, Dict] = {}
    for tag, typ, count, _aliases in rows:
        type_label = E621_TAG_TYPES.get(typ)
        if type_label not in ("general", "species", "meta"):
            continue
        tier_func = TIER_FUNCS.get(type_label)
        if not tier_func:
            continue
        tier = tier_func(count)
        if not tier:
            continue
        cat_label = CATEGORY_LABELS.get(type_label, type_label)
        cat = categories.setdefault(cat_label, {"name": cat_label, "_groups": {}})
        group = cat["_groups"].setdefault(tier, {"name": tier, "tags": {}})
        jp = (
            E621_JP_HINTS.get(tag)
            or jp_hand.get(tag)
            or jp_machine.get(tag)
            or tag
        )
        group["tags"][tag] = jp

    cat_order = ["一般タグ", "種族・形態", "メタタグ（構図・解像度）"]
    ordered: List[Dict] = []
    for cat_name in cat_order:
        cat = categories.get(cat_name)
        if not cat:
            continue
        groups_sorted = sorted(
            cat["_groups"].values(),
            key=lambda g: (g["name"].count("★") * -1, g["name"]),
        )
        for g in groups_sorted:
            g["tags"] = dict(sorted(g["tags"].items(), key=lambda kv: kv[0].lower()))
        ordered.append({"name": cat_name, "groups": groups_sorted})

    return {"name": "e621", "categories": ordered}


# ---- NovelAI v3 / Illustrious quality & rating tokens (hand-curated) ----

NAI_ILLUSTRIOUS_QUALITY = {
    "Illustrious / NoobAI 推奨品質トークン": {
        "masterpiece": "最高品質",
        "best quality": "最高品質",
        "very awa": "非常に優れた構図（illustrious AWA）",
        "very aesthetic": "非常に美しい",
        "aesthetic": "美しい",
        "absurdres": "超高解像度",
        "highres": "高解像度",
        "newest": "最新トレーニング",
        "recent": "最近",
        "old": "古い",
    },
    "Illustrious / NoobAI 推奨レーティング": {
        "rating:general": "全年齢",
        "rating:sensitive": "やや過激",
        "rating:questionable": "微妙な内容",
        "rating:explicit": "成人向け",
        "general": "全年齢タグ",
        "sensitive": "ややセンシティブ",
        "safe": "安全な内容",
    },
    "NovelAI v3 推奨品質トークン": {
        "very aesthetic": "非常に美しい (NAI v3)",
        "aesthetic": "美しい (NAI v3)",
        "displeasing": "不快な構図",
        "very displeasing": "非常に不快な構図",
        "year 2024": "2024 年スタイル",
        "year 2023": "2023 年スタイル",
        "year 2022": "2022 年スタイル",
        "year 2021": "2021 年スタイル",
        "best quality": "最高品質",
        "amazing quality": "驚異的な品質",
        "great quality": "高い品質",
        "good quality": "良い品質",
        "normal quality": "普通の品質",
        "bad quality": "低品質",
        "worst quality": "最悪品質",
    },
    "ネガティブプロンプト定番": {
        "lowres": "低解像度",
        "bad anatomy": "解剖学的に変",
        "bad hands": "手の崩れ",
        "bad fingers": "指の崩れ",
        "extra fingers": "指が多い",
        "extra digits": "指が多い",
        "fewer digits": "指が少ない",
        "blurry": "ぼやけ",
        "watermark": "透かし",
        "signature": "サイン",
        "text": "テキスト混入",
        "jpeg artifacts": "JPEGノイズ",
        "username": "ユーザー名",
        "error": "エラー",
        "cropped": "切れ",
        "ugly": "醜い",
        "duplicate": "複製",
        "morbid": "病的",
        "mutilated": "切断された",
        "out of frame": "枠外",
        "deformed": "変形",
        "disfigured": "崩れた",
        "long neck": "首が長すぎ",
        "extra limbs": "余分な手足",
        "missing arms": "腕欠落",
        "missing legs": "脚欠落",
        "low quality": "低品質",
        "normal quality": "普通の品質（ネガティブ）",
        "worst quality": "最悪品質（ネガティブ）",
        "monochrome": "モノクロ",
        "grayscale": "グレースケール",
    },
    "構図・人数の基本": {
        "1girl": "女の子 1 人",
        "1boy": "男の子 1 人",
        "2girls": "女の子 2 人",
        "2boys": "男の子 2 人",
        "multiple_girls": "複数の女の子",
        "multiple_boys": "複数の男の子",
        "solo": "ソロ",
        "duo": "2 人 (e621)",
        "trio": "3 人",
        "no_humans": "人物なし",
        "from_above": "俯瞰",
        "from_below": "あおり",
        "from_side": "横から",
        "from_behind": "後ろから",
        "cowboy shot": "カウボーイショット (太もも上)",
        "full body": "全身",
        "upper body": "上半身",
        "lower body": "下半身",
        "close-up": "クローズアップ",
        "portrait": "ポートレート",
    },
}


def build_nai_section() -> Dict:
    cats: List[Dict] = []
    for group_name, tags in NAI_ILLUSTRIOUS_QUALITY.items():
        sorted_tags = dict(sorted(tags.items(), key=lambda kv: kv[0].lower()))
        cats.append({"name": group_name, "groups": [{"name": "推奨", "tags": sorted_tags}]})
    return {"name": "NovelAI / Illustrious 推奨タグ", "categories": cats}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=os.path.join(_SCRIPT_DIR, "..", "group_tags", "nai_illustrious.yaml"))
    parser.add_argument("--cache", default=CACHE_DIR)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    e621_path = fetch(E621_CSV_URL, os.path.join(args.cache, "e621.csv"), force=args.force)
    hand_path = fetch(JP_HAND_URL, os.path.join(args.cache, "danbooru-jp.csv"), force=args.force)
    mach_path = fetch(JP_MACHINE_URL, os.path.join(args.cache, "danbooru-machine-jp.csv"), force=args.force)

    rows = load_e621(e621_path)
    jp_hand = load_translations(hand_path)
    jp_mach = load_translations(mach_path)
    print(f"[e621-import] loaded: tags={len(rows)} jp_hand={len(jp_hand)} jp_machine={len(jp_mach)}")

    sections = [build_nai_section(), build_e621_yaml_section(rows, jp_hand, jp_mach)]

    total = 0
    for s in sections:
        for c in s.get("categories") or []:
            for g in c.get("groups") or []:
                total += len(g.get("tags") or {})
    print(f"[e621-import] selected tags: {total}")

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            sections,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )
    print(f"[e621-import] wrote: {out_path}")


if __name__ == "__main__":
    main()
