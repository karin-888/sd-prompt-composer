#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Merge Danbooru tags from 018 into core sections 000-010."""

from __future__ import annotations

import json
import os
import re
import sys
from typing import Any, Dict, Optional, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
_SECTIONS_DIR = os.path.join(_SCRIPT_DIR, "..", "group_tags", "sections")

SOURCE_FILE = "018_danbooru.yaml"

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

NSFW_RE = re.compile(
    r"(^after_(?:vaginal|anal)|"
    r"anal(?:_|$)|anus|vaginal|penis|testicles|pussy|vulva|"
    r"nipples?|areola|breast_sucking|breasts_out|"
    r"cum|ejaculation|semen|facial|creampie|"
    r"masturbat|fingering|fellatio|cunnilingus|paizuri|handjob|footjob|"
    r"sex\b|intercourse|orgasm|"
    r"bondage|bdsm|spanking|groping|"
    r"nude|naked|topless|bottomless|no_panties|no_bra|"
    r"spread_legs|cameltoe|pantyshot|upskirt|"
    r"lactation|pregnant|impregnation|"
    r"futanari|hermaphrodite|"
    r"rape|molestation|"
    r"sex_toy|dildo|vibrator|"
    r"undressing|strip(?:ping)?|"
    r"see-through|see_through|"
    r"x-ray|x_ray|cross-section|cross_section|"
    r"object_insertion|"
    r"audible_internal_cumshot)",
    re.I,
)

FOOD_RE = re.compile(
    r"(^food|_(?:food|drink|tea|coffee|beer|wine|sake|milk|juice|cake|bread|meat|rice|noodle|"
    r"fruit|vegetable|egg|fish|sushi|ramen|bento|snack|candy|chocolate|ice_cream|"
    r"apple|banana|strawberry|carrot|potato|onion|tomato|pizza|burger|sandwich|"
    r"cookie|donut|pie|soup|steak|sausage|corn|melon|grape|peach|cherry|"
    r"mushroom|zongzi|dumpling|onigiri|dango|mochi|tempura|curry)|"
    r"alcohol|bottle(?:$|_)|cup(?:$|_)|plate(?:$|_)|bowl(?:$|_))",
    re.I,
)

CLOTHING_RE = re.compile(
    r"(_(?:uniform|dress|skirt|pants|shorts|shirt|jacket|coat|sweater|vest|"
    r"kimono|yukata|serafuku|sailor|bikini|swimsuit|leotard|bodysuit|"
    r"bra|panties|underwear|thighhighs|stockings|socks|gloves|boots|"
    r"footwear|shoes|sandals|heels|hat|cap|hoodie|scarf|necktie|neckerchief|"
    r"bowtie|ribbon|collar|cape|capelet|apron|armor|helmet|mask|"
    r"headband|hairband|choker|belt|bag|backpack|"
    r"one-piece|one_piece|sleeves|clothes|clothing|outfit|costume|"
    r"lingerie|nightgown|pajamas|robe|suit|blazer|cardigan|"
    r"legwear|leggings|tights|fundoshi|tabard|"
    r"bikini|swimsuit|sports_bra|tank_top|tunic|"
    r"argyle_clothes|blood_on_clothes)(?:$|_|\)|\()|"
    r"^(?:black|white|red|blue|green|yellow|pink|purple|brown|gray|grey|orange|aqua|"
    r"gold|silver|multicolored)_(?:bikini|dress|skirt|shirt|pants|coat|jacket|"
    r"hat|ribbon|bow|bra|panties|kimono|leotard|swimsuit|sweater|vest|"
    r"footwear|gloves|scarf|necktie|hoodie|shorts|serafuku|sailor|"
    r"one-piece_swimsuit|sports_bra|thighhighs|choker|neckerchief|"
    r"cape|collar|hairband|theme))",
    re.I,
)

BG_RE = re.compile(
    r"(background|outdoors|indoors|outside|inside|"
    r"beach|ocean|sea|river|lake|waterfall|pool|bath\b|"
    r"forest|tree|leaf|flower|grass|mountain|sky|cloud|"
    r"night|day|sunset|sunrise|evening|morning|"
    r"city|street|building|school|classroom|bedroom|"
    r"autumn_leaves|snow|rain|"
    r"against_wall|storefront|aircraft|airplane|"
    r"scenery|landscape|garden|park|"
    r"anchor|balloon|fireworks|"
    r"^beachball|^blanket|^bath\b)",
    re.I,
)

OBJECT_RE = re.compile(
    r"(^weapon|sword|gun|rifle|pistol|knife|axe|bow_(?!tie)|arrow|"
    r"shield|staff|wand|hammer|spear|"
    r"ball\b|box\b|bottle|anchor|aircraft|airplane|"
    r"phone|camera|book|pen|pencil|"
    r"umbrella|flag|sign|logo|"
    r"instrument|guitar|piano|"
    r"vehicle|car|train|ship|boat|"
    r"food_request|flower_request|weapon_request|"
    r"zippo|lighter|"
    r"^gear|^cable|^bolt)",
    re.I,
)

ACTION_RE = re.compile(
    r"(looking_|sitting|standing|lying|walking|running|jumping|"
    r"sleeping|eating|drinking|reading|writing|"
    r"smile|smiling|grin|laugh|blush|crying|tears|"
    r"angry|surprised|sleepy|"
    r"arm_|hand_|finger|holding|carry|"
    r"battle|fighting|"
    r"against_wall|bound\b|"
    r"anniversary|birthday|"
    r"zooming_in|zooming_out|"
    r"assertive|"
    r"^battle$|^bath$|^bound$|^zipping$)",
    re.I,
)

CHAR_RE = re.compile(
    r"(^\d+(?:\+)?(?:girl|boy|girls|boys|other)|^solo|^1girl|^1boy|"
    r"^androgynous|^furry|^animal|^robot|^cyborg|"
    r"_(?:hair|eyes|skin|face|nose|mouth|ears|tail|horns|wings|"
    r"fur|pupils|sclera|teeth|tongue|lips|"
    r"breast|pectorals|abs|navel|"
    r"eyebrows|eyelashes|makeup|"
    r"gender|boy|girl)(?:$|_|\)|\()|"
    r"^alternate_(?:hair|eye|color|hairstyle|hair_length|hair_color|eye_color)|"
    r"^colored_skin|^body_|^animal_|^borrowed_character|"
    r"^furry|^kemono|^monster|^ghost|^zombie|"
    r"^heterochromia|^ahoge|^side_ponytail|"
    r"^eyelashes$|^nostrils$|^animalization|^animification|"
    r"^bara$|^yaoi$|^yuri$|^trap$)",
    re.I,
)

RACE_RE = re.compile(
    r"(^elf|^fairy|^demon|^angel|^vampire|^dragon|^slime|"
    r"^cat_(?:girl|boy)|^dog_(?:girl|boy)|^fox_(?:girl|boy)|^wolf_(?:girl|boy)|"
    r"^bunny_girl|^cow_girl|^horse_girl|^bird_girl|^shark_girl|"
    r"^lamia|^harpy|^mermaid|^centaur|^goblin|^orc|"
    r"^kemonomimi|^animal_ears|^cat_ears|^dog_ears|^fox_ears|"
    r"^tail$|_(?:tail|ears|horns|wings)(?:$|_|\)|\())",
    re.I,
)

COMP_RE = re.compile(
    r"(from_(?:above|below|side|behind)|"
    r"_(?:view|angle|shot|perspective|focus|framing)|"
    r"portrait|landscape|close-up|close_up|"
    r"depth_of_field|bokeh|"
    r"lighting|shadow|backlight|"
    r"flash\b|"
    r"symmetry|dutch_angle|"
    r"cropped|out_of_frame|"
    r"looking_at_viewer|eye_contact|"
    r"simple_background|gradient_background|"
    r"black_border|irregular_border|"
    r"alternate_color|colorized|"
    r"blending|impasto|painterly|"
    r"retro_artstyle|"
    r"^animated$|^screenshot$)",
    re.I,
)

QUALITY_RE = re.compile(
    r"(quality|detailed|masterpiece|highres|high_res|"
    r"ai-generated|ai-assisted|"
    r"official_art|scan|"
    r"^flash$)",
    re.I,
)

META_MEDIUM_RE = re.compile(r"(\(medium\)|_(medium)$|photoshop|clip_studio|blender|gimp|procreate|sai_|live2d|ibispaint|paint\.net|zbrush|3ds_max|source_filmmaker|spine_)", re.I)
META_QUALITY_RE = re.compile(r"(bad_|resolution|upscaled|downscaled|jpeg|quality|aspect_ratio|corrupted|lossy|aliasing|banding|md5_mismatch|pixel-perfect)", re.I)
META_COMP_RE = re.compile(r"(tall_image|wide_image|screenshot|key_visual|self-portrait|animated|video|ugoira|cosplay_photo|official_wallpaper|promotional_art|novel_illustration)", re.I)


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


def _cloth_dest(tag: str) -> Dest:
    t = tag.lower()
    if re.search(r"(bikini|swimsuit|one-piece_swimsuit|leotard|bodysuit|sports_bra)", t):
        return ("003_衣装_装飾.yaml", "衣装", "水着")
    if re.search(r"(panties|underwear|bra\b|lingerie|panty)", t):
        return ("009_NSFW.yaml", "NSFW", "服")
    if re.search(r"(kimono|yukata|serafuku|sailor|fundoshi)", t):
        return ("003_衣装_装飾.yaml", "衣装", "和服")
    if re.search(r"(skirt|thighhighs|shorts|pants|legwear|leggings|tights)", t):
        return ("003_衣装_装飾.yaml", "衣装", "ボトムス")
    if re.search(r"(dress|gown|robe|apron|costume)", t):
        return ("003_衣装_装飾.yaml", "衣装", "ドレス")
    if re.search(r"(coat|jacket|cape|capelet|blazer|cardigan|hoodie|vest|sweater)", t):
        return ("003_衣装_装飾.yaml", "衣装", "コート")
    if re.search(r"(hat|cap|hood|hairband|headband|helmet|mask)", t):
        return ("003_衣装_装飾.yaml", "衣服や装飾品", "帽子")
    if re.search(r"(ribbon|bow|necktie|neckerchief|bowtie|choker|scarf|collar|earrings|gloves|bag|belt|footwear|shoes|boots|sandals|socks|stockings)", t):
        return ("003_衣装_装飾.yaml", "衣装", "手袋・アクセサリー")
    if re.search(r"(uniform|serafuku|armor|suit)", t):
        return ("003_衣装_装飾.yaml", "衣装", "制服")
    return ("003_衣装_装飾.yaml", "衣装", "シャツ")


def _map_meta(tag: str) -> Dest:
    t = tag.lower()
    if META_MEDIUM_RE.search(t):
        return ("004_視覚効果.yaml", "画面", "芸術の種類")
    if META_QUALITY_RE.search(t):
        return ("000_画像品質_技術.yaml", "クオリティ", "品質・解像度")
    if META_COMP_RE.search(t):
        return ("004_視覚効果.yaml", "アングル・構図", "特殊な構図")
    if re.search(r"(ai-generated|ai-assisted|translated|commission|pixiv|patreon|fanbox|upscaled|photo-referenced)", t):
        return ("000_画像品質_技術.yaml", "クオリティ", "品質・解像度")
    return ("000_画像品質_技術.yaml", "ネガティブ", "画像品質")


def _map_general(tag: str) -> Dest:
    t = tag.lower()

    if re.match(r"^artist_", t) or t in {"artist_logo", "artist_self-insert", "artist_collaboration"}:
        return ("010_アーティスト.yaml", "NAIv3 / Illustrious XL Artist Style Codex", "Single Artist Style (SMEA True)")

    if NSFW_RE.search(t):
        if re.search(r"(panties|bra|bikini|swimsuit|lingerie|leotard|underwear|clothes|dress|skirt|shirt|uniform|costume|nude|topless|bottomless)", t):
            return ("009_NSFW.yaml", "NSFW", "服")
        if re.search(r"(expression|face|blush|ahegao|orgasm|saliva|tongue|open_mouth)", t):
            return ("009_NSFW.yaml", "NSFW", "表情・顔")
        if re.search(r"(pose|standing|sitting|lying|spread|on_back|on_side|all_fours|straddle)", t):
            return ("009_NSFW.yaml", "NSFW", "動作・ポーズ")
        if re.search(r"(penis|testicles|cum|ejaculation|semen)", t):
            return ("009_NSFW.yaml", "NSFW", "ペニス")
        if re.search(r"(pussy|vulva|vaginal|anus|anal)", t):
            return ("009_NSFW.yaml", "NSFW", "女性器")
        if re.search(r"(breast|nipple|areola|paizuri|lactation)", t):
            return ("009_NSFW.yaml", "NSFW", "乳・乳輪・ピアス")
        if re.search(r"(bondage|bound|bdsm|collar|leash|spanking)", t):
            return ("009_NSFW.yaml", "NSFW", "緊縛・BDSM")
        return ("009_NSFW.yaml", "NSFW", "特殊・シチュエーション")

    if FOOD_RE.search(t):
        return ("007_食べ物.yaml", "食べ物・飲み物", "食べ物・飲み物")

    if CLOTHING_RE.search(t):
        return _cloth_dest(tag)

    if re.match(r"^\d+(?:\+)?(?:girl|boy|girls|boys|other)s?$", t) or t in {"solo", "1girl", "1boy", "2girls", "2boys"}:
        return ("001_キャラクター.yaml", "人物像", "人数")

    if RACE_RE.search(t):
        return ("008_ジャンル_世界観.yaml", "ファンタジー", "亜人・種族")

    if CHAR_RE.search(t):
        if re.search(r"(hair|ahoge|ponytail|braid|side_ponytail|alternate_hair|alternate_hairstyle)", t):
            return ("001_キャラクター.yaml", "人物", "髪の毛")
        if re.search(r"(eyes|eyelash|sclera|pupil|eyebrow|heterochromia|alternate_eye)", t):
            return ("001_キャラクター.yaml", "顔パーツ", "目の形状")
        if re.search(r"(face|nose|mouth|lips|teeth|tongue|nostril|makeup|blush)", t):
            return ("001_キャラクター.yaml", "顔パーツ", "基本")
        if re.search(r"(skin|fur|body_|breast|pectoral|abs|navel|colored_skin|blue_skin|red_skin)", t):
            return ("001_キャラクター.yaml", "人物", "体型")
        if re.search(r"(tail|ears|horns|wings|animal_|robot|cyborg|furry|kemono)", t):
            return ("008_ジャンル_世界観.yaml", "ファンタジー", "亜人・種族")
        if t in {"bara", "yaoi", "yuri", "trap"}:
            return ("001_キャラクター.yaml", "人物", "身分")
        return ("001_キャラクター.yaml", "人物", "キャラクター")

    if BG_RE.search(t):
        if re.search(r"(cloud|sky|sunset|sunrise|night|day|evening|morning|rain|snow|autumn)", t):
            return ("006_背景_環境.yaml", "背景", "天候・時間帯")
        if re.search(r"(tree|forest|leaf|flower|grass|plant|garden|autumn_leaves)", t):
            return ("006_背景_環境.yaml", "植物・自然", "植物")
        if re.search(r"(beach|ocean|sea|river|lake|water|pool|bath\b|waterfall)", t):
            return ("006_背景_環境.yaml", "環境", "水")
        if re.search(r"(city|street|building|school|classroom|storefront|indoor|bedroom)", t):
            return ("006_背景_環境.yaml", "背景", "都市・建物")
        if re.search(r"background|simple_background|gradient", t):
            return ("006_背景_環境.yaml", "背景", "背景色・効果")
        return ("006_背景_環境.yaml", "シーン", "屋外")

    if OBJECT_RE.search(t):
        if re.search(r"(sword|gun|rifle|pistol|knife|axe|bow_(?!tie)|arrow|shield|staff|wand|hammer|spear|weapon)", t):
            return ("005_小物_道具.yaml", "アイテム", "武器")
        if re.search(r"(aircraft|airplane|vehicle|car|train|ship|boat)", t):
            return ("005_小物_道具.yaml", "アイテム", "その他のアイテム")
        return ("005_小物_道具.yaml", "アイテム", "その他のアイテム")

    if ACTION_RE.search(t):
        if re.search(r"(smile|grin|laugh|blush|cry|tear|angry|surprised|sleepy|expression)", t):
            return ("002_動作_表現.yaml", "表情動作", "その他表情")
        if re.search(r"(looking_|gaze|eye_contact)", t):
            return ("004_視覚効果.yaml", "アングル・構図", "視線")
        if re.search(r"(sitting|lying|sleeping|squat|kneel|seiza)", t):
            return ("002_動作_表現.yaml", "基本動作・ポーズ", "座り・横たわり")
        if re.search(r"(walking|running|jumping|battle|fighting|against_wall)", t):
            return ("002_動作_表現.yaml", "基本動作・ポーズ", "移動・運動")
        if re.search(r"(arm_|hand_|finger|holding|carry|zipping)", t):
            return ("002_動作_表現.yaml", "基本動作・ポーズ", "手の動き・ジェスチャー")
        return ("002_動作_表現.yaml", "基本動作・ポーズ", "日常動作")

    if COMP_RE.search(t):
        if re.search(r"(lighting|shadow|backlight|flash\b)", t):
            return ("004_視覚効果.yaml", "アングル・構図", "ライティング")
        if re.search(r"(looking_|gaze|eye_contact|from_)", t):
            return ("004_視覚効果.yaml", "アングル・構図", "視線")
        if re.search(r"(background|border|colorized|blending|impasto|painterly|retro)", t):
            return ("004_視覚効果.yaml", "画面", "芸術スタイル")
        return ("004_視覚効果.yaml", "アングル・構図", "視点・角度")

    if QUALITY_RE.search(t):
        return ("000_画像品質_技術.yaml", "クオリティ", "品質・解像度")

    if re.search(r"(meme|_(?:fate|kancolle|idolmaster|blue_archive|genshin|pokemon|touhou|fire_emblem|azur_lane|arknights|fate|sao|konosuba|overwatch|project_moon))", t):
        return ("001_キャラクター.yaml", "人物", "二次元キャラクター")

    return ("001_キャラクター.yaml", "人物", "キャラクター")


def _map_dest(top_cat: str, group_name: str, tag: str) -> Dest:
    cn = top_cat or ""
    if cn == "キャラクター":
        return ("001_キャラクター.yaml", "人物", "二次元キャラクター")
    if cn == "作品名":
        return ("001_キャラクター.yaml", "人物", "二次元キャラクター")
    if cn == "メタタグ（品質・構図）":
        return _map_meta(tag)
    return _map_general(tag)


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
                    stats["errors"].append(f"{fname}/{cat_name}/{group_name} <- {cn}/{gn}/{key}")
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
        os.remove(os.path.join(_SECTIONS_DIR, SOURCE_FILE))
        sys.path.insert(0, _TOOLS_DIR)
        from rebuild_manifest import rebuild
        stats["manifest"] = rebuild()

    return stats


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    print(json.dumps(merge(dry_run=dry), ensure_ascii=False, indent=2))
