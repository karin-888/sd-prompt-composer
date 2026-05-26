#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Merge tags from 031 personal dictionary into core sections 000-008."""

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

SOURCE_FILE = "031_個人辞書_google_drive_xlsx.yaml"

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

Dest = Tuple[str, str, str]  # filename, category, group

HAIR_STYLE_KW = (
    "ponytail", "pigtail", "twintail", "twin_drill", "braid", "twists", "weave",
    "bun", "chignon", "updo", "curl", "wave", "perm", "blowout", "bob", "lob",
    "fringe", "bangs", "sidelock", "shag", "pixie", "mohawk", "mullet", "fade",
    "undercut", "dread", "afro", "quiff", "pompadour", "_hair", "haircut", "hair_updo",
    "hair_bun", "drill_hair", "ahoge", "hair_tubes",
)

NSFW_KW = (
    "sex", "cum", "semen", "penis", "pussy", "nipple", "nude", "anal", "bdsm",
    "bondage", "ahegao", "orgasm", "fellatio", "paizuri", "vaginal", "tentacle",
    "breast_smother", "gag", "shibari", "missionary", "doggystyle", "futa", "cfnm",
    "cmnf", "slut", "whore", "cockslut", "erectile", "crotchless", "areolae",
    "ejacu", "assless", "bottom_less", "bottomless", "pee", "urination", "pubic_tattoo",
    "dripping_semen", "pussy_cum", "pussy_line", "cum_in", "panties", "microbikini",
    "frill_panties", "skindantation", "public_indecency", "intercourse", "boy_on_top",
    "girl_on_top", "straddling", "apron, nude", "orgasm", "ecstacy", "bitch",
)

NEG_KW = (
    "worst_quality", "low_quality", "bad_", "neg:", "easynegative", "missing_finger",
    "extra_digit", "watermark", "signature", "username", "artist_name", "loli", "young/",
    "gay:", "futa/futanari", "as-adult-neg", "as-young", "badhand", "badneg",
)

BG_KW = (
    "background", "forest", "beach", "onsen", "shrine", "outdoors", "sky", "clouds",
    "waterfall", "lake", "nature", "stage", "field", "road", "car_seat", "bed_room",
    "air_bed", "pool", "building", "room", "tatami", "shoji", "coast", "athletic_field",
    "sand", "tree", "branch", "pond", "wind", "autumn", "petal", "sakura", "night_pool",
    "drydock", "card_background", "bright_background",
)

CLOTHING_KW = (
    "dress", "skirt", "shirt", "bikini", "uniform", "armor", "maid", "panties", "coat",
    "sweater", "jacket", "apron", "swimsuit", "leotard", "thong", "overalls", "corset",
    "garter", "pantyhose", "thighhigh", "heels", "cheerleader", "nurse", "witch",
    "gym_suit", "buruma", "china_dress", "idol_dress", "randoseru", "backpack",
    "casual_wear", "microbikini", "argyle", "sheer", "overcoat", "ribbed",
)

FANTASY_KW = (
    "cat_ears", "fox_ears", "wolf_ears", "demon_", "pointy_ears", "tail", "horns",
    "wings", "mecha_musume", "elf", "gort_ears", "squirrel_ears", "animal_ears",
)

FOOD_KW = ("food_photography", "food_", "_food", "sushi", "ramen", "bread_", "cake_")


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


def _hair_group(tag: str) -> str:
    t = _tag_key(tag)
    if any(k in t for k in ("ponytail", "pigtail")):
        return "ポニーテイル"
    if "twintail" in t or "twin_drill" in t or "drill_hair" in t:
        return "ツインテール"
    if any(k in t for k in ("braid", "twists", "weave")):
        return "三つ編み"
    if any(k in t for k in ("bun", "chignon", "updo", "space_bun")):
        return "お団子"
    if any(k in t for k in ("curl", "wave", "perm", "blowout")):
        return "巻き毛"
    if "bob" in t or "lob" in t:
        return "ボブ"
    if any(k in t for k in ("fringe", "bangs", "sidelock")):
        return "前髪"
    if any(k in t for k in ("short", "pixie", "buzz", "crew_cut", "skinhead", "bold_girl")):
        return "ショート"
    if any(k in t for k in ("gradient_hair", "colored_tips", "split-color", "two-tone", "streaked", "multicolored_hair", "rainbow_hair", "dip-dye", "pastel-colored_hair")):
        return "髪の色"
    if t.endswith("_color") or "_color" in t.split(",")[0]:
        return "髪の色"
    if any(k in t for k in ("colored_inner", "split-color", "streaked", "multicolored", "pastel-colored")):
        return "髪の色"
    if "_hair" in t or t.endswith("_hair") or any(k in t for k in HAIR_STYLE_KW):
        return "特殊な髪型"
    return "その他"


def _nsfw_group(tag: str) -> str:
    t = _tag_key(tag)
    if "tentacle" in t:
        return "触手"
    if any(k in t for k in ("bondage", "shibari", "bdsm", "bound", "restrained", "gag")):
        return "緊縛・BDSM"
    if any(k in t for k in ("fellatio", "paizuri", "double_fellatio", "stealth_paizuri", "breast_smother")):
        return "フェラ・イラマチオ・キス"
    if any(k in t for k in ("doggystyle", "missionary", "straddling", "sex_from_behind", "sex,", "intercourse", "vaginal", "boy_on_top", "girl_on_top")):
        return "性行為・体位"
    if any(k in t for k in ("pee", "urination", "放尿")):
        return "おしっこ・放尿・おもらし"
    if any(k in t for k in ("cum", "semen", "pussy_cum", "dripping", "ejacu", "areolae")):
        return "体液・状態"
    if any(k in t for k in ("dress", "bikini", "uniform", "armor", "maid", "nude", "apron", "swimsuit", "leotard", "cheerleader", "nurse", "witch", "gym", "buruma", "china_dress", "thong", "overalls", "corset", "panties", "bottom_less", "crotchless", "assless")):
        return "服"
    if any(k in t for k in ("ahegao", "blush", "orgasm", "ecstacy", "expression", "vulgarity", "sexual_ecstasy", "naughty", "bitch", "slut", "drivel")):
        return "表情・顔"
    if any(k in t for k in ("lying", "on_stomach", "doggystyle", "recumbent", "caswling", "crawling")):
        return "動作・ポーズ"
    return "特殊・シチュエーション"


def _negative_group(tag: str) -> Tuple[str, str]:
    t = _tag_key(tag)
    if "as-young" in t:
        return "ネガティブなプロンプト", "人物"
    if any(k in t for k in ("as-adult-neg", "easynegative", "badhand", "badneg", "baddream")):
        return "ネガティブなプロンプト", "Embeddings"
    if any(k in t for k in ("finger", "hand", "anatomy", "limb", "face", "child", "loli", "young", "fat", "ugly")):
        return "ネガティブ", "人物の問題"
    return "ネガティブ", "画像品質"


def _background_group(tag: str) -> Tuple[str, str]:
    t = _tag_key(tag)
    if any(k in t for k in ("onsen", "bath", "tatami", "shoji", "room", "indoor", "bed_room", "air_bed")):
        return "シーン", "屋内"
    if any(k in t for k in ("shrine", "building", "city", "road", "stage", "car")):
        return "シーン", "都市"
    if any(k in t for k in ("forest", "beach", "lake", "waterfall", "nature", "pond", "tree", "field", "coast", "sand", "autumn", "petal", "pool")):
        return "シーン", "屋外"
    if any(k in t for k in ("sky", "cloud", "midair", "in_sky")):
        return "環境", "空"
    if "bubble" in t or "atmosphere" in t:
        return "環境", "雰囲気"
    return "背景", "自然"


def _map_source(cat: str, group: str) -> Optional[Dest]:
    cn, gn = cat or "", group or ""

    if cn == "4. 表情・雰囲気":
        return ("001_キャラクター.yaml", "表情", gn or "その他の表情")

    if cn == "6. 口・顔・アクセサリー":
        if gn == "舌":
            return ("001_キャラクター.yaml", "顔パーツ", "舌")
        return ("001_キャラクター.yaml", "顔パーツ", "口の動作")

    if cn == "10. 服装・小物":
        if "唐風" in gn:
            return ("003_衣装_装飾.yaml", "漢服", "唐風")
        if "宋風" in gn:
            return ("003_衣装_装飾.yaml", "漢服", "宋風")
        if "明風" in gn:
            return ("003_衣装_装飾.yaml", "漢服", "明風")

    if cn == "12. SEX":
        nsfw = {
            "SEX・表情・顔": "表情・顔",
            "SEX・動作・ポーズ": "動作・ポーズ",
            "SEX・体位・プレイ": "体位・プレイ",
            "触手": "触手",
            "バイブ・性玩具・道具": "性玩具・道具",
            "SEX・ 服": "服",
        }
        if gn in nsfw:
            return ("009_NSFW.yaml", "NSFW", nsfw[gn])

    if cn == "14. 背景・環境":
        return ("006_背景_環境.yaml", "環境", "雰囲気")

    if cn == "20. ネガティブ":
        return ("000_画像品質_技術.yaml", "ネガティブ", "画像品質")

    if cn == "21. ファンタジー":
        if gn == "亜人の耳":
            return ("008_ジャンル_世界観.yaml", "ファンタジー", "耳")

    if cn == "プロンプト2025-12-28":
        return ("004_視覚効果.yaml", "画面", gn)

    if cn == "髪型(別冊)":
        hm = {
            "色": "髪の色", "前髪": "前髪", "その他": "その他", "全体": "特殊な髪型",
            "ポニーテール系": "ポニーテイル", "ツインテール系": "ツインテール",
            "三つ編み系": "三つ編み", "お団子系": "お団子", "巻き毛系": "巻き毛",
        }
        if gn in hm:
            return ("001_キャラクター.yaml", "髪パーツ", hm[gn])

    if cn == "プロンプトまとめ":
        pm: Dict[str, Dest] = {
            "〇クオリティ": ("000_画像品質_技術.yaml", "クオリティ", "品質・解像度"),
            "〇ネガティブ": ("000_画像品質_技術.yaml", "ネガティブ", "画像品質"),
            "〇年齢": ("001_キャラクター.yaml", "人物像", "年齢"),
            "〇髪型・女子": ("001_キャラクター.yaml", "髪パーツ", "ツインテール"),
            "〇キャラクター": ("001_キャラクター.yaml", "人物", "キャラクター"),
            "髪色": ("001_キャラクター.yaml", "髪パーツ", "髪の色"),
            "髪、複数色": ("001_キャラクター.yaml", "髪パーツ", "髪の色"),
        }
        if gn in pm:
            return pm[gn]
        if gn == "Sheet6":
            return None  # NSFW – classify per tag
        if gn == "〇人物1":
            return None  # body – classify per tag

    if cn == "pronpt":
        pm2: Dict[str, Optional[Dest]] = {
            "Sheet8": ("001_キャラクター.yaml", "表情", "笑顔・笑い"),
            "Sheet9": ("001_キャラクター.yaml", "髪パーツ", "お団子"),
            "Sheet7": ("004_視覚効果.yaml", "アングル・構図", "視点・角度"),
            "Sheet5": ("003_衣装_装飾.yaml", "衣装", "ドレス"),
            "エロ": None,
            "Sheet6": None,
        }
        if gn in pm2:
            return pm2[gn]

    return None


def _classify_tag(tag: str, cat: str, group: str) -> Dest:
    t = _tag_key(tag)
    cn, gn = cat or "", group or ""

    if cn == "12. SEX" or gn == "エロ" or (cn == "プロンプトまとめ" and gn == "Sheet6"):
        return ("009_NSFW.yaml", "NSFW", _nsfw_group(tag))

    if any(k in t for k in NSFW_KW):
        return ("009_NSFW.yaml", "NSFW", _nsfw_group(tag))

    if cn == "20. ネガティブ" or gn in ("〇ネガティブ", "ネガティブ") or any(k in t for k in NEG_KW):
        cat_neg, grp_neg = _negative_group(tag)
        return ("000_画像品質_技術.yaml", cat_neg, grp_neg)

    if cn == "プロンプトまとめ" and gn == "〇クオリティ" or any(k in t for k in ("masterpiece", "best_quality", "8k", "4k", "detailed", "highres", "uhd", "ultra", "quality", "high_resolusion", "low-res")):
        if not any(k in t for k in NSFW_KW + CLOTHING_KW):
            return ("000_画像品質_技術.yaml", "クオリティ", "品質・解像度")

    if any(k in t for k in FOOD_KW):
        return ("007_食べ物.yaml", "食べ物・飲み物", "食べ物・飲み物")

    if cn == "21. ファンタジー" or any(k in t for k in FANTASY_KW):
        if "ear" in t:
            return ("008_ジャンル_世界観.yaml", "ファンタジー", "耳")
        if "tail" in t:
            return ("008_ジャンル_世界観.yaml", "ファンタジー", "尻尾")
        if any(k in t for k in ("horn", "demon")):
            return ("008_ジャンル_世界観.yaml", "ファンタジー", "ツノ・角")
        if "wing" in t or "mecha_musume" in t:
            return ("008_ジャンル_世界観.yaml", "ファンタジー", "翼")
        return ("008_ジャンル_世界観.yaml", "ファンタジー", "亜人・種族")

    if cn == "14. 背景・環境" or any(k in t for k in BG_KW):
        bg_cat, bg_grp = _background_group(tag)
        return ("006_背景_環境.yaml", bg_cat, bg_grp)

    if cn == "10. 服装・小物" or gn in ("Sheet5",) or any(k in t for k in CLOTHING_KW):
        if any(k in t for k in ("shoe", "heel", "boot", "sandal")):
            return ("003_衣装_装飾.yaml", "衣装", "靴")
        if any(k in t for k in ("glasses", "eyewear")):
            return ("003_衣装_装飾.yaml", "衣服や装飾品", "メガネ")
        if "swimsuit" in t or "bikini" in t:
            return ("003_衣装_装飾.yaml", "衣装", "水着")
        if "uniform" in t or "serafuku" in t or "school" in t:
            return ("003_衣装_装飾.yaml", "衣装", "制服")
        if "maid" in t:
            return ("003_衣装_装飾.yaml", "衣装", "コスチューム・特殊衣装")
        if "dress" in t or "gown" in t:
            return ("003_衣装_装飾.yaml", "衣装", "ドレス")
        if "skirt" in t:
            return ("003_衣装_装飾.yaml", "衣装", "スカート")
        if any(k in t for k in ("panties", "thong", "garter", "pantyhose", "thighhigh", "sock")):
            return ("003_衣装_装飾.yaml", "衣装", "靴下")
        return ("003_衣装_装飾.yaml", "衣装", "シャツ")

    if cn in ("髪型(別冊)",) or gn in ("Sheet9", "〇髪型・女子", "髪色", "髪、複数色") or (cn == "プロンプトまとめ" and gn == "〇Sheet2" and (_hair_group(tag) != "その他" or "_color" in t or "_hair" in t)):
        if cn == "プロンプトまとめ" and gn == "〇Sheet2" and t.endswith("_color"):
            return ("004_視覚効果.yaml", "色・色彩", "基本色")
        return ("001_キャラクター.yaml", "髪パーツ", _hair_group(tag))

    if cn == "4. 表情・雰囲気" or gn == "Sheet8" or any(k in t for k in ("smile", "laugh", "joy", "grin", "cry", "tear", "blush", "angry", "expression", "ahegao")):
        if any(k in t for k in ("laugh", "joy", "smile", "grin", "cracking")):
            return ("001_キャラクター.yaml", "表情", "笑顔・笑い")
        if "blush" in t:
            return ("001_キャラクター.yaml", "表情", "照れ・恥ずかしさ")
        if "angry" in t:
            return ("001_キャラクター.yaml", "表情", "怒り・不機嫌")
        return ("002_動作_表現.yaml", "表情動作", "その他表情")

    if gn == "Sheet7" or any(k in t for k in ("angle", "view", "shot", "pov", "focus_on", "close_to_viewer", "in_the_distance", "upside-down", "facing_at_viewer", "point_at_viewer", "ass_focus", "hip_focus", "single_focus", "couple_focus")):
        if any(k in t for k in ("light", "lit", "lighting", "shutter")):
            return ("004_視覚効果.yaml", "アングル・構図", "ライティング")
        return ("004_視覚効果.yaml", "アングル・構図", "視点・角度")

    if any(k in t for k in ("pose", "sitting", "standing", "lying", "sit,", "couple_sitting", "folded_legs", "a_pose", "mirror", "smartphone", "selfie", "wind", "floating_hair")):
        if any(k in t for k in ("sitting", "couple_sitting", "sit")):
            return ("002_動作_表現.yaml", "基本動作・ポーズ", "座り・横たわり")
        if any(k in t for k in ("mirror", "smartphone", "selfie", "camera")):
            return ("002_動作_表現.yaml", "基本動作・ポーズ", "特殊なポーズ・表現")
        return ("002_動作_表現.yaml", "基本動作・ポーズ", "基本姿勢")

    if cn == "プロンプト2025-12-28" or any(k in t for k in ("painting", "sketch", "watercolor", "illustration", "anime", "manga", "1980s", "1990s", "art_", "medium", "style", "impasto", "dieselpunk", "pixel", "cg", "photograph", "sepia", "acrylic", "ink", "pen", "pastel", "pointillism", "ukiyoe", "oil_painting", "classicism", "dadaism", "futurism", "mucha", "monet")):
        if any(k in t for k in ("classicism", "dadaism", "futurism", "abstract")):
            return ("004_視覚効果.yaml", "画面", "芸術派")
        if any(k in t for k in ("mucha", "monet", "artist")):
            return ("004_視覚効果.yaml", "画面", "アーティストのスタイル")
        if any(k in t for k in ("watercolor", "oil_painting", "ink", "wash_painting", "impasto", "dyeing")):
            return ("004_視覚効果.yaml", "画面", "芸術の種類")
        if any(k in t for k in ("pen", "pencil", "marker", "acrylic", "ballpoint", "millipen", "colored_pencil", "graphite")):
            return ("004_視覚効果.yaml", "画面", "ペン")
        if any(k in t for k in ("sketch", "outline", "greyscale", "monochrome")):
            return ("004_視覚効果.yaml", "画面", "スケッチ")
        return ("004_視覚効果.yaml", "画面", "芸術スタイル")

    if t.endswith("_color") or re.search(r"(?<![a-z])color(?![a-z])", t):
        return ("004_視覚効果.yaml", "色・色彩", "基本色")

    if any(k in t for k in ("eye", "pupil", "iris", "eyelash", "makeup", "lip", "tongue", "mouth", "teeth", "nose")):
        if any(k in t for k in ("glasses", "eyewear")):
            return ("003_衣装_装飾.yaml", "衣服や装飾品", "メガネ")
        if "makeup" in t or "rouge" in t or "lipstick" in t or "mascara" in t or "eyeliner" in t:
            return ("001_キャラクター.yaml", "顔パーツ", "メイク")
        if any(k in t for k in ("sparkling", "glazed", "highlight_eyes", "drunked_eyes")):
            return ("001_キャラクター.yaml", "顔パーツ", "目の効果")
        if "eye" in t or "pupil" in t:
            return ("001_キャラクター.yaml", "顔パーツ", "目の表情")
        if "lip" in t or "mouth" in t:
            return ("001_キャラクター.yaml", "顔パーツ", "唇")
        if "tongue" in t:
            return ("001_キャラクター.yaml", "顔パーツ", "舌")
        if "makeup" in t:
            return ("001_キャラクター.yaml", "顔パーツ", "メイク")
        return ("001_キャラクター.yaml", "顔パーツ", "口の表情")

    if any(k in t for k in ("skin", "breast", "thigh", "abdomen", "navel", "muscle", "body", "fighter", "athlete")):
        if any(k in t for k in ("breast", "thigh", "abdomen", "navel")):
            return ("001_キャラクター.yaml", "身体パーツ", "胸部")
        if "skin" in t:
            return ("001_キャラクター.yaml", "身体パーツ", "肌")
        return ("001_キャラクター.yaml", "人物", "キャラクター")

    if any(k in t for k in ("1girl", "1boy", "1man", "1lady", "1female", "couple", "solo", "girl", "boy", "man", "female", "male", "hairy_man", "feminine_boy")):
        return ("001_キャラクター.yaml", "人物像", "人数")

    if any(k in t for k in ("weapon", "sword", "gun", "rifle")):
        return ("005_小物_道具.yaml", "アイテム", "武器")

    if any(k in t for k in ("smartphone", "mirror", "backpack", "pom_poms")):
        return ("005_小物_道具.yaml", "アイテム", "その他のアイテム")

    if cn == "プロンプトまとめ" and gn == "〇Sheet2":
        if t.endswith("_color"):
            return ("004_視覚効果.yaml", "色・色彩", "基本色")
        return ("001_キャラクター.yaml", "髪パーツ", _hair_group(tag))

    return ("001_キャラクター.yaml", "人物", "キャラクター")


def merge(*, dry_run: bool = False) -> Dict:
    sections = {f: _load_section(f) for f in TARGET_FILES}
    source = _load_section(SOURCE_FILE)
    existing = _existing_keys(sections)
    stats = {"added": 0, "skipped": 0, "by_target": {}, "errors": []}

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
                dest = _map_source(cn, gn)
                if dest is None:
                    dest = _classify_tag(str(key), cn, gn)
                fname, cat_name, group_name = dest
                target = _find_group(sections[fname], cat_name, group_name)
                if not target:
                    stats["errors"].append(f"{fname}/{cat_name}/{group_name} <- {key[:40]}")
                    continue
                if not dry_run:
                    target.setdefault("tags", {})[str(key)] = value
                existing[nk] = dest
                stats["added"] += 1
                label = f"{fname}/{cat_name}/{group_name}"
                stats["by_target"][label] = stats["by_target"].get(label, 0) + 1

    if stats["errors"]:
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
