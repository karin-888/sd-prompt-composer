#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Merge Civitai popular prompt tags (012-017) into core sections 000-010."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
_SECTIONS_DIR = os.path.join(_SCRIPT_DIR, "..", "group_tags", "sections")

SOURCE_FILES = [
    "012_civitai_人気プロンプト_illustrious.yaml",
    "013_civitai_人気プロンプト_pony_sdxl_anime.yaml",
    "014_civitai_人気プロンプト_sdxl.yaml",
    "015_civitai_人気プロンプト_flux_1.yaml",
    "017_civitai_人気プロンプト_other.yaml",
]

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
    "010_アーティスト.yaml",
]

Dest = Tuple[str, str, str]

ARTIST_GROUP = ("010_アーティスト.yaml", "NAIv3 / Illustrious XL Artist Style Codex", "Single Artist Style (SMEA True)")

TAG_MAP: Dict[str, Dest] = {
    "kaela_kovalskia": ("001_キャラクター.yaml", "人物", "二次元キャラクター"),
    "frieren": ("001_キャラクター.yaml", "人物", "二次元キャラクター"),
    "gawr_gura": ("001_キャラクター.yaml", "人物", "二次元キャラクター"),
    "princess_zelda": ("001_キャラクター.yaml", "人物", "二次元キャラクター"),
    "concept_art": ("004_視覚効果.yaml", "画面", "芸術の種類"),
    "anime_screenshot": ("004_視覚効果.yaml", "画面", "芸術スタイル"),
    "anime_screencap": ("004_視覚効果.yaml", "画面", "芸術スタイル"),
    "source_furry": ("008_ジャンル_世界観.yaml", "ファンタジー", "亜人・種族"),
    "medium_breast": ("001_キャラクター.yaml", "人物", "胸部"),
    "soresu_stance": ("002_動作_表現.yaml", "基本動作・ポーズ", "戦闘・格闘"),
    "sword_pointed_forward": ("002_動作_表現.yaml", "基本動作・ポーズ", "戦闘・格闘"),
    "sword_raised_behind_head": ("002_動作_表現.yaml", "基本動作・ポーズ", "戦闘・格闘"),
    "two_fingers": ("002_動作_表現.yaml", "基本動作・ポーズ", "手の動き・ジェスチャー"),
    "elbows_on_knees": ("002_動作_表現.yaml", "基本動作・ポーズ", "しゃがみ・跪き"),
    "looking_at_the_viewer": ("004_視覚効果.yaml", "アングル・構図", "視線"),
    "looking_away": ("004_視覚効果.yaml", "アングル・構図", "視線"),
    "eyes_closed": ("002_動作_表現.yaml", "表情動作", "その他表情"),
    "sitting_girl": ("002_動作_表現.yaml", "基本動作・ポーズ", "座り・横たわり"),
}


def _tag_key(tag: str) -> str:
    return (tag or "").strip().lower()


def _load_section(filename: str) -> Dict:
    with open(os.path.join(_SECTIONS_DIR, filename), encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    return data[0] if isinstance(data, list) else {}


def _save_section(filename: str, section: Dict) -> None:
    path = os.path.join(_SECTIONS_DIR, filename)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fp:
        yaml.dump([section], fp, allow_unicode=True, sort_keys=False, width=120)
    os.replace(tmp, path)


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
        if fname in SOURCE_FILES:
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


def _is_quality(tag: str) -> bool:
    t = tag.lower()
    if re.search(r"score_\d", t):
        return True
    if re.search(r"(quality|detailed|resolution|masterpiece|8k|4k|uhd|hd\b|lazypos|lazyup|illusp|ilxl|usnr|bw9t|smooth_quality|enhanceimage|overalldetail|hyperdetailed|hyper_detailed|hyper-detailed|tack_sharp|raw_photo|sfw|newest|aesthetic|microcontrast|segmented|good_anatomy|good_hands|good_fingers|perfect_anatomy|clean_anatomy)", t):
        return True
    return False


def _is_clothing(tag: str) -> bool:
    t = tag.lower()
    return bool(re.search(r"(_dress|_skirt|_footwear|_tunic|_tank_top|thighhigh|thigh_strap|satin_attire|long_magical_dress|hair_ribbon|ribbon\b)", t))


def _is_character(tag: str) -> bool:
    t = tag.lower()
    if re.search(r"^(1_girl|1woman|adult_woman|solo_female|cute_girl|beautiful_woman|athletic|slender_body|furry|anthro|robot|cybernetic|horns|sclera|eyelash|eyeshadow|nostril|colored_skin|red_skin|animal\b|no_human|princess|elemental|oni|axolotl|jawa|troubadour)", t):
        return True
    if re.search(r"(_hair|_eyes|_face|_body|_fur|_skin|_nose|_ears|_hands|_horns|_pupil|_eyelash|_breast|_wings|_lips|_makeup|_complexion|_torso|shoulders|hands\b|fair_skin|pale_porcelain)", t):
        return True
    return False


def _is_background(tag: str) -> bool:
    t = tag.lower()
    return bool(re.search(r"(background|clouds?|trees|willow|evening|outside|storefront|forest|glacier|canal|indoor|industrial_setting|beige_background|negative_space|mountain|ocean|arctic|parchment|branches|leaves|flowers_in_hair|sakura|venetian|urban|street|room|bedroom|pool|castle|garden|waterfall|sky|dawn|night|moonlit|solitude|tall_trees)", t))


def _is_object(tag: str) -> bool:
    t = tag.lower()
    return bool(re.search(r"(sword|wires|cables|gears|bolts|crystals|feather|heart\b|map\b|octopus|lantern|bowl|armor|plate|weapon|phone|camera|origami)", t))


def _is_action(tag: str) -> bool:
    t = tag.lower()
    return bool(re.search(r"(looking_|squatting|stance|pose|expression|gesture|sitting|standing|hug|kiss|embrace|fight|combat|pointed|raised|fingers|head_bowed|captured_mid|drawing_the|gazing|piercing_intense_gaze|overhanging|calm_melancholic|compassionate|affectionate|dramatic_pose|meditative|sorrowful|cheerful|adventurous|eyes_closed|shooting_line|side_profile|fullbody|full_body)", t))


def _is_food(tag: str) -> bool:
    return bool(re.search(r"(food|drink|meal|snack|cake|coffee|tea\b|fruit|sushi|ramen)", tag, re.I))


def _is_artist_style(tag: str) -> bool:
    t = tag.lower()
    if re.search(r"(in_the_style_of|style_of|styled_by|art_style|artist\b|zidiusart|bradhamel|greg_rutkowski|rembrandt|daniel_merriam|nihonga|ukiyo|midjourney|artstation|cknc|cksc|ck-mgs|pingtu|fancha|del1cate_balance|748cmstyle|aosiai123|pinkretroanime|pinkflux|db4rz|novuschroma|neopigma|nistyle|nixport|caico|hyfpunk|animaport|crystal_zit|ed_painterly|posingdynamics|an1mel1nes|animeniji|inkpunk|linquivera|illustration-fen|aidmamj|t-kay|civchan|chb3hi3|jeddtl02|moonlit)", t):
        return True
    return False


def _is_composition_lighting(tag: str) -> bool:
    t = tag.lower()
    if _is_quality(tag) or _is_clothing(tag) or _is_character(tag) or _is_background(tag):
        return False
    if re.search(r"(composition|lighting|light\b|shadow|angle|perspective|focus|depth_of_field|bokeh|lens|shot|view|frame|framing|portrait|close-up|close_up|rule_of_thirds|symmetr|centered|vertical|horizontal|low_angle|high_angle|side_view|front_view|full_view|zoom|crop|silhouette|atmosphere|ambient|volumetric|ray_trac|cinematic|dramatic|color_grad|palette|contrast|halation|bloom|rim_light|chiaroscuro|exposure|grading|diffusion|haze|glow|reflection|highlight|rolloff|bokeh|photography|photoreal|macro|50mm|anamorphic|long_exposure|double_exposure|film_grain|analog|octane|unreal_engine|render|hdr|dynamic_range|global_illumination|ambient_occlusion)", t):
        return True
    return False


def _is_art_style(tag: str) -> bool:
    t = tag.lower()
    if re.search(r"(anime|manga|watercolor|oil_painting|digital_art|illustration|painterly|impasto|line_art|lineless|cel_shading|flat_color|vector|mosaic|minimalism|lineart|ink|sketch|retro|fantasy|surreal|dream|ethereal|whimsical|ghibli|renaissance|impression|expression|abstract|sculptural|maximalist|semireal|semi-real|realism|hyper.?real|photoreal|studio_anime|splash_art|concept|horror|sci-fi|dark_fantasy|magical|moe\b|poetic|modern_art|silhouette_art|sumi-e|nihonga|ukiyo|inkpunk|ink_illustration|brush_stroke|brushstroke|canvas|impasto|segmented|flatline|geometric|crystal|botanical|eco-fantasy|fairytale|noir|vintage|editorial|vogue|blockbuster|risograph|pop-art|watercolour)", t):
        return True
    return False


def _map_dest(cat_name: str, group_name: str, tag: str) -> Dest:
    gn = group_name or ""
    if tag in TAG_MAP:
        return TAG_MAP[tag]

    if gn == "絵師":
        return ARTIST_GROUP
    if gn == "キャラ":
        return ("001_キャラクター.yaml", "人物", "二次元キャラクター")
    if gn == "メタ":
        if "concept" in tag.lower():
            return ("004_視覚効果.yaml", "画面", "芸術の種類")
        return ("004_視覚効果.yaml", "画面", "芸術スタイル")

    t = tag.lower()
    if _is_food(tag):
        return ("007_食べ物.yaml", "食べ物・飲み物", "食べ物・飲み物")
    if _is_clothing(tag):
        if re.search(r"(_skirt|thighhigh|thigh_strap|bottom|pants|shorts)", t):
            return ("003_衣装_装飾.yaml", "衣装", "ボトムス")
        if "_dress" in t or "magical_dress" in t:
            return ("003_衣装_装飾.yaml", "衣装", "ドレス")
        if re.search(r"(ribbon|accessory|tank_top|tunic|attire|armor|plate)", t):
            return ("003_衣装_装飾.yaml", "衣装", "アクセサリー・小物")
        return ("003_衣装_装飾.yaml", "衣装", "シャツ")
    if _is_object(tag):
        if re.search(r"sword|weapon|armor|plate", t):
            return ("005_小物_道具.yaml", "アイテム", "武器")
        return ("005_小物_道具.yaml", "アイテム", "その他のアイテム")
    if _is_action(tag):
        if re.search(r"expression|melancholic|compassionate|affectionate|eerie|cheerful|eyes_closed|gaze|smile|mouth", t):
            return ("002_動作_表現.yaml", "表情動作", "その他表情")
        if re.search(r"(fight|combat|sword|stance|pointed|raised)", t):
            return ("002_動作_表現.yaml", "基本動作・ポーズ", "戦闘・格闘")
        if re.search(r"(finger|hand|gesture)", t):
            return ("002_動作_表現.yaml", "基本動作・ポーズ", "手の動き・ジェスチャー")
        if re.search(r"(sitting|squatting|full_body|fullbody)", t):
            return ("002_動作_表現.yaml", "基本動作・ポーズ", "座り・横たわり")
        return ("002_動作_表現.yaml", "基本動作・ポーズ", "特殊なポーズ・表現")
    if _is_character(tag):
        if re.search(r"(_hair|braid|ahoge|hairstyle|hair_ribbon)", t):
            return ("001_キャラクター.yaml", "人物", "髪の毛")
        if re.search(r"(_eyes|_eyelash|_sclera|pupil|gaze)", t):
            return ("001_キャラクター.yaml", "顔パーツ", "目の形状")
        if re.search(r"(_face|_nose|_lips|_makeup|_complexion|nostril)", t):
            return ("001_キャラクター.yaml", "顔パーツ", "基本")
        if re.search(r"(_skin|colored_skin|red_skin|fur\b|robot|cybernetic|anthro|furry|horns|wings|oni|elemental|princess|breast|body|athletic|slender)", t):
            return ("001_キャラクター.yaml", "人物", "体型")
        if re.search(r"^(1_girl|1woman|adult_woman|solo_female|cute_girl|beautiful_woman)", t):
            return ("001_キャラクター.yaml", "人物像", "人数")
        return ("001_キャラクター.yaml", "人物", "キャラクター")
    if _is_background(tag):
        if re.search(r"(cloud|sky|dawn|evening|weather|sunset|night|moonlit)", t):
            return ("006_背景_環境.yaml", "背景", "天候・時間帯")
        if re.search(r"(tree|forest|leaf|branch|flower|garden|plant|willow|botanical|sakura|mountain|ocean|water|canal|glacier|arctic)", t):
            return ("006_背景_環境.yaml", "植物・自然", "植物")
        if re.search(r"(urban|street|storefront|industrial|venetian|architecture|building|castle|room|indoor)", t):
            return ("006_背景_環境.yaml", "背景", "都市・建物")
        if re.search(r"(background|negative_space|beige_background|color_palette)", t):
            return ("006_背景_環境.yaml", "背景", "背景色・効果")
        return ("006_背景_環境.yaml", "シーン", "屋外")
    if _is_quality(tag):
        if re.search(r"(bad_|worst_|low_|jpeg|artifact|anatomy|hands|fingers|limb|negative|no_readable_text|no_text|no_watermark|no_logo)", t):
            return ("000_画像品質_技術.yaml", "ネガティブ", "画像品質")
        return ("000_画像品質_技術.yaml", "クオリティ", "品質・解像度")
    if _is_artist_style(tag):
        if re.match(r"^[a-z0-9_-]+$", tag) and len(tag) < 24 and not re.search(r"(style|painting|art)", t):
            return ARTIST_GROUP
        return ("004_視覚効果.yaml", "画面", "アーティストのスタイル")
    if _is_composition_lighting(tag):
        if re.search(r"(lighting|light\b|shadow|illumination|occlusion|rembrandt|ambient|volumetric|golden_hour|studio_light)", t):
            return ("004_視覚効果.yaml", "アングル・構図", "ライティング")
        if re.search(r"(lens|50mm|anamorphic|bokeh|depth_of_field|macro|exposure|film_grain|halation|chromatic)", t):
            return ("004_視覚効果.yaml", "アングル・構図", "レンズ・効果")
        if re.search(r"(composition|rule_of_thirds|framing|centered|symmetr|portrait_format|vertical|diagonal|close-up|close_up|shot|view|angle|perspective|focus|silhouette)", t):
            return ("004_視覚効果.yaml", "アングル・構図", "特殊な構図")
        if re.search(r"(looking_|gaze|eye_level|from_above|from_below|side_view|front_view|back_view|high_angle|low_angle)", t):
            return ("004_視覚効果.yaml", "アングル・構図", "視点・角度")
        return ("004_視覚効果.yaml", "アングル・構図", "フォーカス")
    if _is_art_style(tag):
        if re.search(r"(oil|watercolor|ink|sketch|canvas|brush|impasto|line_art|lineless|flat_|vector|segmented|minimal|abstract|sculptural|renaissance|sumi|nihonga|ukiyo|ghibli|anime|moe\b|fantasy|surreal|dream|horror|sci-fi|dark_fantasy|magical|retro|vintage|editorial|photoreal|realism|3d_render|render|octane|unreal)", t):
            return ("004_視覚効果.yaml", "画面", "芸術スタイル")
        if re.search(r"(atmosphere|mood|serene|mysterious|eerie|cozy|epic|dramatic|romantic|peaceful|melancholic|intense|energy|glowing|halation|ethereal)", t):
            return ("004_視覚効果.yaml", "色・色彩", "基本色")
        return ("004_視覚効果.yaml", "画面", "芸術の種類")
    if re.search(r"(fantasy|horror|sci-fi|robot|magical|dystopian|dark_fantasy|cosmic|fairytale|anthro|furry|elemental|oni|cyberpunk|steampunk|futuristic|renaissance|medieval|samurai|ronin|venetian|asian|japanese|chinese|european)", t):
        return ("008_ジャンル_世界観.yaml", "ファンタジー", "亜人・種族")
    if re.search(r"(nsfw|explicit|nude|naked|breast|pussy|sex)", t):
        return ("009_NSFW.yaml", "NSFW", "特殊・シチュエーション")

    return ("004_視覚効果.yaml", "画面", "芸術スタイル")


def _store_value(fname: str, value: Any) -> Any:
    if fname == "010_アーティスト.yaml":
        if isinstance(value, dict):
            return value
        text = str(value) if value is not None else ""
        return {"jp": text, "preview": ""}
    return value


def merge(*, dry_run: bool = False) -> Dict:
    sections = {f: _load_section(f) for f in TARGET_FILES}
    existing = _existing_keys(sections)
    stats = {"added": 0, "skipped": 0, "by_target": {}, "errors": []}

    for source_file in SOURCE_FILES:
        source = _load_section(source_file)
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
                        stats["errors"].append(f"{fname}/{cat_name}/{group_name} <- {source_file}/{gn}/{key}")
                        continue
                    if not dry_run:
                        target.setdefault("tags", {})[str(key)] = _store_value(fname, value)
                    existing[nk] = (fname, cat_name, group_name)
                    stats["added"] += 1
                    label = f"{fname}/{cat_name}/{group_name}"
                    stats["by_target"][label] = stats["by_target"].get(label, 0) + 1

    if stats["errors"]:
        stats["errors"] = stats["errors"][:30]
        return stats

    if not dry_run:
        for fname in TARGET_FILES:
            _save_section(fname, sections[fname])
        for source_file in SOURCE_FILES:
            os.remove(os.path.join(_SECTIONS_DIR, source_file))
        sys.path.insert(0, _TOOLS_DIR)
        from rebuild_manifest import rebuild
        stats["manifest"] = rebuild()

    return stats


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    print(json.dumps(merge(dry_run=dry), ensure_ascii=False, indent=2))
