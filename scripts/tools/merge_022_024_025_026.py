#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Merge 022/024/025/026 prompt dictionary tags into core sections 000-010."""

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

SOURCE_FILES = [
    "022_ai美女プロンプト辞典_note_com_ai_image_goat.yaml",
    "024_grokエロプロンプト集_mania_romptn_com.yaml",
    "025_ai生成メモネーロ_memone-ro_com.yaml",
    "026_metacamp_abyss_meta-camp_net.yaml",
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


def _store_value(fname: str, value: Any) -> Any:
    if fname == "010_アーティスト.yaml":
        if isinstance(value, dict):
            return value
        return {"jp": str(value) if value is not None else "", "preview": ""}
    return value


def _nsfw_by_tag(tag: str) -> Dest:
    t = tag.lower()
    if re.search(r"(expression|face|blush|ahegao|orgasm|saliva|tongue|smile|grin|tear|gaze|eye)", t):
        return ("009_NSFW.yaml", "NSFW", "表情・顔")
    if re.search(r"(pose|standing|sitting|lying|spread|knees|legs|butt|ass|hip|on_knees|bending)", t):
        return ("009_NSFW.yaml", "NSFW", "動作・ポーズ")
    if re.search(r"(penis|cock|testicles|cum|ejaculation|semen|handjob|fellatio|cunnilingus|fingering|masturbat|paizuri|sex|intercourse|position|missionary|doggy|cowgirl)", t):
        if re.search(r"(penis|cock|testicles|cum|ejaculation|semen)", t):
            return ("009_NSFW.yaml", "NSFW", "ペニス")
        if re.search(r"(position|missionary|doggy|cowgirl|intercourse|sex)", t):
            return ("009_NSFW.yaml", "NSFW", "性行為・体位")
        return ("009_NSFW.yaml", "NSFW", "フェラ・イラマチオ・キス")
    if re.search(r"(pussy|vulva|vaginal|anal|anus|crotch|panties|underwear|bra|panty|camel|underboob|sideboob|breast|nipple|areola|cleavage)", t):
        if re.search(r"(breast|nipple|areola|cleavage|underboob|sideboob|paizuri)", t):
            return ("009_NSFW.yaml", "NSFW", "乳・乳輪・ピアス")
        if re.search(r"(panties|underwear|bra|lingerie|panty|underwear|garter|fishnet|stockings|thighhigh)", t):
            return ("009_NSFW.yaml", "NSFW", "服")
        if re.search(r"(anal|anus)", t):
            return ("009_NSFW.yaml", "NSFW", "アヌス・尻穴")
        return ("009_NSFW.yaml", "NSFW", "女性器")
    if re.search(r"(bondage|slave|collar|leash|bdsm|restraint|blindfold|gag|chain|shackle)", t):
        return ("009_NSFW.yaml", "NSFW", "緊縛・BDSM")
    if re.search(r"(vibrator|dildo|toy|plug)", t):
        return ("009_NSFW.yaml", "NSFW", "性玩具・道具")
    if re.search(r"(pee|urine|sweat|fluid|wet|glistening)", t):
        return ("009_NSFW.yaml", "NSFW", "体液・状態")
    return ("009_NSFW.yaml", "NSFW", "特殊・シチュエーション")


def _cloth_dest(tag: str, group: str = "") -> Dest:
    t = tag.lower()
    g = group or ""
    if re.search(r"(bikini|swimsuit|leotard|high.?leg|highleg|one.?piece.*swim)", t) or "水着" in g or "ハイレグ" in g:
        return ("003_衣装_装飾.yaml", "衣装", "水着")
    if re.search(r"(panties|underwear|bra|lingerie|garter|fishnet|pantyhose|stockings|thighhigh|socks|panty)", t) or "下着" in g or "ガーター" in g or "網タイツ" in g or "ストッキング" in g or "パンスト" in g:
        if "NSFW" in g or re.search(r"(see.?through|sheer|transparent|no_bra|nude|exposed|nipple|underwear)", t):
            return ("009_NSFW.yaml", "NSFW", "服")
        return ("003_衣装_装飾.yaml", "衣装", "靴下")
    if re.search(r"(kimono|yukata|serafuku|sailor|fundoshi|wa_|和服|浴衣)", t) or "和服" in g or "セーラー" in g or "浴衣" in g:
        return ("003_衣装_装飾.yaml", "衣装", "和服")
    if re.search(r"(maid|bunny|nurse|costume|cosplay|uniform|serafuku|blazer|school)", t) or "メイド" in g or "バニー" in g or "ナース" in g or "制服" in g or "コスプレ" in g:
        return ("003_衣装_装飾.yaml", "衣装", "制服")
    if re.search(r"(dress|gown|robe|slit|cutout)", t) or "ドレス" in g or "スリット" in g:
        return ("003_衣装_装飾.yaml", "衣装", "ドレス")
    if re.search(r"(skirt|shorts|pants|bottom|hot_pants|legwear)", t) or "スカート" in g:
        return ("003_衣装_装飾.yaml", "衣装", "ボトムス")
    if re.search(r"(coat|jacket|hoodie|sweater|cardigan|vest|blazer|apron)", t) or "セーター" in g or "コート" in g:
        return ("003_衣装_装飾.yaml", "衣装", "コート")
    if re.search(r"(hat|cap|headwear|hair_ornament|ribbon|bow|necktie|scarf|gloves|bag|belt|earring|accessory|choker|frill|lace)", t) or "アクセサリー" in g or "リボン" in g or "帽子" in g or "髪飾り" in g:
        return ("003_衣装_装飾.yaml", "衣装", "アクセサリー・小物")
    if re.search(r"(shirt|top|blouse|tank|tunic|camisole)", t) or "シャツ" in g or "トップス" in g:
        return ("003_衣装_装飾.yaml", "衣装", "シャツ")
    return ("003_衣装_装飾.yaml", "衣装", "コスチューム・特殊衣装")


def _map_022(top_cat: str, group: str, tag: str) -> Dest:
    cn = top_cat or ""
    gn = group or ""
    if "第1章" in cn:
        if "リアル" in gn:
            return ("004_視覚効果.yaml", "レンズ", "レンズ")
        return ("004_視覚効果.yaml", "画面", "芸術スタイル")
    if "第2章" in cn:
        if "ヘア" in gn:
            return ("001_キャラクター.yaml", "人物", "髪の毛")
        if "メイク" in gn:
            return ("001_キャラクター.yaml", "顔パーツ", "基本")
        return ("001_キャラクター.yaml", "顔パーツ", "目の形状")
    if "第3章" in cn:
        if "胸" in gn:
            return ("001_キャラクター.yaml", "人物", "胸部")
        if "肌" in gn:
            return ("001_キャラクター.yaml", "人物", "皮膚")
        return ("001_キャラクター.yaml", "人物", "体型")
    if "第4章" in cn:
        if "水着" in gn or "リゾート" in gn:
            return ("003_衣装_装飾.yaml", "衣装", "水着")
        if "和服" in gn:
            return ("003_衣装_装飾.yaml", "衣装", "和服")
        if "制服" in gn or "コスプレ" in gn:
            return ("003_衣装_装飾.yaml", "衣装", "制服")
        if "ランジェリー" in gn or "部屋着" in gn:
            return ("009_NSFW.yaml", "NSFW", "服")
        if "フォーマル" in gn:
            return ("003_衣装_装飾.yaml", "衣装", "ドレス")
        if "アクセサリー" in gn:
            return ("003_衣装_装飾.yaml", "衣装", "アクセサリー・小物")
        return ("003_衣装_装飾.yaml", "衣装", "カジュアル・部屋着")
    if "第5章" in cn:
        if "表情" in gn:
            return ("002_動作_表現.yaml", "表情動作", "その他表情")
        if "視線" in gn:
            return ("004_視覚効果.yaml", "アングル・構図", "視線")
        return ("002_動作_表現.yaml", "基本動作・ポーズ", "特殊なポーズ・表現")
    if "第6章" in cn:
        if "距離" in gn:
            return ("004_視覚効果.yaml", "アングル・構図", "フォーカス")
        if "アングル" in gn:
            return ("004_視覚効果.yaml", "アングル・構図", "視点・角度")
        return ("004_視覚効果.yaml", "アングル・構図", "特殊な構図")
    if "第7章" in cn:
        if "室内" in gn:
            return ("006_背景_環境.yaml", "シーン", "屋内")
        return ("006_背景_環境.yaml", "シーン", "屋外")
    if "第8章" in cn:
        if "自然光" in gn:
            return ("004_視覚効果.yaml", "アングル・構図", "ライティング")
        return ("004_視覚効果.yaml", "アングル・構図", "ライティング")
    if "第9章" in cn:
        if "天候" in gn or "季節" in gn or "時間帯" in gn:
            return ("006_背景_環境.yaml", "背景", "天候・時間帯")
        if "色味" in gn:
            return ("004_視覚効果.yaml", "色・色彩", "基本色")
        return ("004_視覚効果.yaml", "画面", "芸術スタイル")
    if "第11章" in cn:
        if "人数" in gn or "年齢" in gn:
            return ("001_キャラクター.yaml", "人物像", "人数")
        if "素材" in gn:
            return ("004_視覚効果.yaml", "画面", "芸術スタイル")
        return ("004_視覚効果.yaml", "アングル・構図", "レンズ・効果")
    if "付録" in cn:
        return ("000_画像品質_技術.yaml", "クオリティ", "品質・解像度")
    if "第14章" in cn or "NSFW" in cn:
        return ("009_NSFW.yaml", "NSFW", "体液・状態")
    if "Don'ts" in gn or "Don't" in cn:
        return ("000_画像品質_技術.yaml", "ネガティブ", "画像品質")
    if "Do's" in gn:
        return ("000_画像品質_技術.yaml", "クオリティ", "品質・解像度")
    return ("004_視覚効果.yaml", "画面", "芸術スタイル")


def _map_024(top_cat: str, group: str, tag: str) -> Dest:
    gn = group or ""
    cn = top_cat or ""
    if re.search(r"(Grok|ChatGPT|Gemini|DeepSeek|Ani|Mika|Rudi|Fun|Normal|Spicy)", tag, re.I) and len(tag) < 20:
        return ("000_画像品質_技術.yaml", "クオリティ", "品質・解像度")
    if "ネガティブ" in gn:
        return ("000_画像品質_技術.yaml", "ネガティブ", "画像品質")
    if "品質" in gn or "クオリティ" in gn or "リアルな実写" in cn:
        if "人物" in gn or "キャラクター" in gn:
            return ("001_キャラクター.yaml", "人物", "キャラクター")
        if "髪型" in gn:
            return ("001_キャラクター.yaml", "人物", "髪の毛")
        if "構図" in gn or "アングル" in gn or "視線" in gn:
            return ("004_視覚効果.yaml", "アングル・構図", "視点・角度")
        if "背景" in gn:
            return ("006_背景_環境.yaml", "シーン", "屋外")
        return ("000_画像品質_技術.yaml", "クオリティ", "品質・解像度")
    if "表情" in gn or "視線" in gn:
        if "NSFW" in cn or "透け" in cn or "胸ちら" in cn or "下乳" in cn or "ノーブラ" in cn:
            return ("009_NSFW.yaml", "NSFW", "表情・顔")
        return ("002_動作_表現.yaml", "表情動作", "その他表情")
    if "ポーズ" in gn or "構図" in gn or "アングル" in gn:
        if any(k in cn for k in ("下乳", "胸ちら", "透け", "めく", "グラビア", "お尻", "むちむち", "体格差", "筋肉", "低身長", "体型", "ハイレグ", "スリット", "奴隷", "エロい服装", "OL", "体型チェック", "お尻突き出し")):
            return ("009_NSFW.yaml", "NSFW", "動作・ポーズ")
        return ("002_動作_表現.yaml", "基本動作・ポーズ", "特殊なポーズ・表現")
    if "背景" in gn or "シーン" in gn or "学校" in gn or "屋外" in gn or "季節" in gn:
        return ("006_背景_環境.yaml", "シーン", "屋外" if "屋外" in gn or "通学" in gn else "屋内")
    if "小物" in gn or "聴診器" in gn or "道具" in gn:
        return ("005_小物_道具.yaml", "アイテム", "その他のアイテム")
    if any(k in gn for k in ("水着", "ビキニ", "レオタード", "ハイレグ", "下着", "ブラ", "パンティ", "ランジェリー", "ガーター", "網タイツ", "ストッキング", "セーラー", "メイド", "ナース", "バニー", "奴隷", "衣装", "素材", "柄", "フリル", "レース", "リボン", "装飾", "靴", "足元", "襟", "スカート", "袖", "カーディガン", "コスプレ", "Cute Maid", "Victorian", "Maid costume", "Traditional Maid", "Better Maid")):
        return _cloth_dest(tag, gn)
    if any(k in cn for k in ("下乳", "胸ちら", "透け", "めく", "ノーブラ", "エロい服装", "奴隷", "ハイレグ", "お尻", "胸の大きさ", "長乳", "むちむち", "低身長", "筋肉", "体格差", "OL職場", "NSFW", "rating", "レーティング")):
        return _nsfw_by_tag(tag)
    if "胸" in gn:
        return ("009_NSFW.yaml", "NSFW", "乳・乳輪・ピアス")
    if "ネガティブ" in cn:
        return ("000_画像品質_技術.yaml", "ネガティブ", "画像品質")
    if "アニメ系" in cn:
        return ("004_視覚効果.yaml", "画面", "芸術スタイル")
    return _nsfw_by_tag(tag) if re.search(r"(breast|nipple|panties|underwear|ass|butt|cleavage|exposed|nude|see.?through|lift|downblouse|underboob)", tag, re.I) else ("002_動作_表現.yaml", "基本動作・ポーズ", "日常動作")


def _map_025(top_cat: str, group: str, tag: str) -> Dest:
    cn = top_cat or ""
    gn = group or ""
    if cn == "髪" or "髪" in cn:
        return ("001_キャラクター.yaml", "人物", "髪の毛")
    if cn == "目":
        return ("001_キャラクター.yaml", "顔パーツ", "目の形状")
    if cn == "表情":
        return ("002_動作_表現.yaml", "表情動作", "その他表情")
    if cn in ("眉毛", "鼻", "指"):
        return ("001_キャラクター.yaml", "顔パーツ", "基本")
    if cn == "肌の色":
        return ("001_キャラクター.yaml", "人物", "皮膚")
    if cn in ("女性の体", "男性の体", "乳・おっぱい", "マンコ", "チンコ", "陰毛", "アナル"):
        return _nsfw_by_tag(tag)
    if cn in ("女性用下着", "男性用下着", "透けてる服"):
        return ("009_NSFW.yaml", "NSFW", "服")
    if cn in ("帽子", "メガネ", "髪飾り・髪留め"):
        return ("003_衣装_装飾.yaml", "衣装", "髪飾り・頭飾り")
    if cn in ("パンスト", "靴下"):
        return ("003_衣装_装飾.yaml", "衣装", "靴下")
    if cn == "シャツ":
        return ("003_衣装_装飾.yaml", "衣装", "シャツ")
    if cn == "ドレス":
        return ("003_衣装_装飾.yaml", "衣装", "ドレス")
    if cn == "ベスト":
        return ("003_衣装_装飾.yaml", "衣装", "コート")
    if cn == "スポーツ衣装":
        return ("003_衣装_装飾.yaml", "衣装", "スポーツウェア")
    if cn == "セーター":
        return ("003_衣装_装飾.yaml", "衣装", "コート")
    if cn == "雨具":
        return ("005_小物_道具.yaml", "アイテム", "その他のアイテム")
    if cn == "スーツ":
        return ("003_衣装_装飾.yaml", "衣装", "正装・制服")
    if cn in ("ズボン", "半ズボン"):
        return ("003_衣装_装飾.yaml", "衣装", "ボトムス")
    if cn == "スカート":
        return ("003_衣装_装飾.yaml", "衣装", "スカート")
    if cn == "着てるものが破れる":
        return ("009_NSFW.yaml", "NSFW", "服")
    if cn in ("バニー", "猫娘", "メイド", "魔女", "シスター", "人魚", "ふたなり", "人型の魔物・モンスター娘"):
        return ("008_ジャンル_世界観.yaml", "ファンタジー", "亜人・種族")
    if cn in ("フェラ", "セックス", "オナニー", "手コキ", "触手", "レイプ", "大人の玩具", "おしっこ", "ガラスに押し付ける", "催眠・常識変換", "縛り・拘束", "落とし穴・感覚遮断落とし穴"):
        return _nsfw_by_tag(tag)
    if cn in ("床", "壁", "カーテン", "自然環境", "建物・施設", "室内", "シンプル背景", "温泉・お風呂"):
        if "温泉" in cn or "お風呂" in cn:
            return ("006_背景_環境.yaml", "シーン", "屋内")
        if "自然" in cn:
            return ("006_背景_環境.yaml", "植物・自然", "植物")
        if "室内" in cn or "床" in cn or "壁" in cn or "カーテン" in cn:
            return ("006_背景_環境.yaml", "シーン", "屋内")
        return ("006_背景_環境.yaml", "背景", "都市・建物")
    if cn in ("戦闘動作", "移動動作"):
        return ("002_動作_表現.yaml", "基本動作・ポーズ", "戦闘・格闘" if "戦闘" in cn else "移動・運動")
    if cn == "○○×○○ 二人の関係":
        return ("001_キャラクター.yaml", "人物像", "人数")
    if cn == "食品関連":
        return ("007_食べ物.yaml", "食べ物・飲み物", "食べ物・飲み物")
    if cn == "マンガ・コミック":
        return ("004_視覚効果.yaml", "画面", "芸術の種類")
    if cn == "塗り":
        return ("004_視覚効果.yaml", "画面", "芸術スタイル")
    if cn == "描かないもの":
        return ("000_画像品質_技術.yaml", "ネガティブ", "画像品質")
    if cn == "ネガティブプロンプト":
        return ("000_画像品質_技術.yaml", "ネガティブ", "画像品質")
    if cn == "クリスマス":
        return ("008_ジャンル_世界観.yaml", "ファンタジー", "亜人・種族")
    return ("001_キャラクター.yaml", "人物", "キャラクター")


def _map_026(top_cat: str, group: str, tag: str) -> Dest:
    cn = top_cat or ""
    gn = group or ""
    if any(k in cn for k in ("NSFW入門", "フェチ", "胸プロンプト", "お尻突き出し", "OL職場NSFW", "NSFW表情", "NSFW前戯", "NSFW体位")):
        return _nsfw_by_tag(tag)
    if "美少女639選" in cn:
        if "年齢" in gn or "体型" in gn:
            return ("001_キャラクター.yaml", "人物", "体型")
        if "顔立ち" in gn or "表情" in gn:
            return ("001_キャラクター.yaml", "顔パーツ", "基本")
        if "髪型" in gn or "髪色" in gn:
            return ("001_キャラクター.yaml", "人物", "髪の毛")
        if "衣装" in gn or "装飾" in gn:
            return _cloth_dest(tag, gn)
        if "ポーズ" in gn or "アクション" in gn:
            return ("002_動作_表現.yaml", "基本動作・ポーズ", "特殊なポーズ・表現")
        if "感情" in gn or "雰囲気" in gn:
            return ("002_動作_表現.yaml", "表情動作", "その他表情")
        if "背景" in gn:
            return ("006_背景_環境.yaml", "シーン", "屋内" if "室内" in gn else "屋外")
        if "世界観" in gn:
            return ("008_ジャンル_世界観.yaml", "ファンタジー", "亜人・種族")
        if "カメラ" in gn or "構図" in gn:
            return ("004_視覚効果.yaml", "アングル・構図", "視点・角度")
        if "照明" in gn or "色合い" in gn:
            return ("004_視覚効果.yaml", "アングル・構図", "ライティング")
        if "品質" in gn or "画風" in gn or "アーティスト" in gn:
            if "アーティスト" in gn:
                return ARTIST_GROUP
            return ("000_画像品質_技術.yaml", "クオリティ", "品質・解像度")
    if "スレンダー" in cn:
        return ("001_キャラクター.yaml", "人物", "体型")
    if "靴下" in cn or "タイツ" in cn or "パンスト" in cn:
        return ("003_衣装_装飾.yaml", "衣装", "靴下")
    if "全身衣装" in cn:
        return _cloth_dest(tag, gn)
    if "カメラアングル" in cn:
        return ("004_視覚効果.yaml", "アングル・構図", "視点・角度")
    if "体型チェック" in cn:
        if "衣装" in gn:
            return ("003_衣装_装飾.yaml", "衣装", "水着")
        if "アングル" in gn or "構図" in gn:
            return ("004_視覚効果.yaml", "アングル・構図", "視点・角度")
        return ("002_動作_表現.yaml", "基本動作・ポーズ", "特殊なポーズ・表現")
    return _nsfw_by_tag(tag)


def _map_dest(source_file: str, top_cat: str, group: str, tag: str) -> Dest:
    if source_file.startswith("022_"):
        return _map_022(top_cat, group, tag)
    if source_file.startswith("024_"):
        return _map_024(top_cat, group, tag)
    if source_file.startswith("025_"):
        return _map_025(top_cat, group, tag)
    if source_file.startswith("026_"):
        return _map_026(top_cat, group, tag)
    return ("004_視覚効果.yaml", "画面", "芸術スタイル")


def merge(*, dry_run: bool = False) -> Dict:
    sections = {f: _load_section(f) for f in TARGET_FILES}
    existing = _existing_keys(sections)
    stats = {"added": 0, "skipped": 0, "by_target": {}, "errors": [], "by_source": {}}

    for source_file in SOURCE_FILES:
        source = _load_section(source_file)
        src_added = 0
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
                    fname, cat_name, group_name = _map_dest(source_file, cn, gn, str(key))
                    target = _find_group(sections[fname], cat_name, group_name)
                    if not target:
                        stats["errors"].append(f"{fname}/{cat_name}/{group_name} <- {source_file}/{gn}/{key}")
                        continue
                    if not dry_run:
                        target.setdefault("tags", {})[str(key)] = _store_value(fname, value)
                    existing[nk] = (fname, cat_name, group_name)
                    stats["added"] += 1
                    src_added += 1
                    label = f"{fname}/{cat_name}/{group_name}"
                    stats["by_target"][label] = stats["by_target"].get(label, 0) + 1
        stats["by_source"][source_file] = src_added

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
