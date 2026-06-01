#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Merge ai-nante tags from 010 into core sections 000-009."""

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

SOURCE_FILE = "010_ai-nante.yaml"

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

NSFW_CAT = [
    "下着デザイン",
    "M字開脚",
    "グラビアポーズ",
    "パンティライン",
    "透けブラ",
    "透視メガネ",
    "服を脱ぐ",
    "服の隙間",
    "体操服×ブルマ",
    "胸を押し付ける",
    "絶対領域",
    "くの一）のプロンプト集（セクシー",
    "快楽や恍惚",
    "誘惑・魅惑",
    "舐める仕草",
    "日焼けした肌・日焼け跡",
    "へそ出しコーデ",
]

BG_CAT = [
    "背景",
    "教室編",
    "ホテル",
    "壁のプロンプト",
    "ドアのプロンプト",
    "窓のプロンプト",
    "床の模様",
    "地面のプロンプト",
    "建築",
    "ストリート・街並み",
    "海・ビーチ",
    "植物・花・樹木",
    "天気・天候",
    "城のプロンプト",
    "軍事施設",
    "和室",
    "キャラの部屋",
    "店内",
    "電車内",
    "文化祭",
    "お花見",
    "正月",
    "節分",
    "ひな祭り",
    "バレンタイン",
    "クリスマス",
    "ハロウィン",
    "サンタコスプレ",
    "キャンプ",
    "娯楽施設",
    "階段のプロンプト",
    "道のプロンプト",
    "場所・空間",
    "シンプルな背景",
    "カーテンに隠れる",
    "観覧車",
    "ナイトクラブ",
    "アパート",
    "ジオラマ",
    "群衆",
    "送電線",
    "自販機",
    "学校の背景",
    "保健室",
    "体育倉庫",
    "破壊シーン",
    "星空・流星",
    "火・炎",
    "水たまり",
    "都市の背景",
    "アイドルのステージ",
    "ミニチュアワークスペース",
    "閉じ込められる",
]

FOOD_CAT = ["アイスの種類", "食べる・食事", "酒を飲む"]

CLOTHING_CAT = [
    "服",
    "ファッション",
    "コーデ",
    "衣装",
    "制服",
    "ドレス",
    "スカート",
    "シャツ",
    "Tシャツ",
    "コート",
    "ジャケット",
    "ジャンパースカート",
    "水着",
    "スクール水着",
    "体操服",
    "和服",
    "浴衣",
    "振袖",
    "袴",
    "巫女服",
    "チャイナ",
    "民族衣装",
    "伝統衣装",
    "メイド",
    "ナース",
    "警察官",
    "軍服",
    "ミリタリー",
    "鎧",
    "甲冑",
    "コスプレ",
    "着ぐるみ",
    "ランジェ",
    "下着",
    "ブラ",
    "ガーター",
    "ペチコート",
    "パジャマ",
    "靴",
    "靴下",
    "タイツ",
    "パンスト",
    "リボン",
    "フリル",
    "柄・模様",
    "配色",
    "素材・質感",
    "部位名称",
    "装飾",
    "重ね着",
    "破れた服",
    "濡れる",
    "はだけ",
    "スリット",
    "ネックライン",
    "隙間",
    "脱ぐ",
    "チラ",
    "スリット",
    "ピチピチ",
    "エナメル",
    "エプロン",
    "レオタード",
    "ボディコン",
    "y2k",
    "ゴシックファッション",
    "ロリータ",
    "デコラ",
    "ヒップホップ",
    "ストリートファッション",
    "エモファッション",
    "ゆめかわ",
    "病みかわ",
    "天使界隈",
    "姫カジ",
    "大正ロマン",
    "昭和レトロ",
    "SF服",
    "近未来",
    "ファンタジー世界の服",
    "原始人の服",
    "腰布",
    "ふんどし",
    "タバード",
    "はっぴ",
    "ボレロ",
    "アロハ",
    "キャミソール",
    "チアリーダー",
    "野球部",
    "バレー",
    "陸上",
    "バイクスーツ",
    "レーシング",
    "ウェディング",
    "OL服",
    "女子大生",
    "デート用",
    "お嬢様ファッション",
    "かっこいい服",
    "かっこいい作業着",
    "豪華な服",
    "地味",
    "春コーデ",
    "冬服",
    "カジュアル服",
    "ファッションショー",
    "ファッション系",
    "トップス服",
    "ショートパンツ",
    "パンツ・ズボン",
    "ズームレイヤー",
    "ワンピース",
    "ポンチョ",
    "マーチング",
    "サンバ",
    "フィギュアスケート",
    "レースクイーン",
    "防護服",
    "特攻服",
    "卒ラン",
    "患者服",
    "探偵",
    "修道服",
    "シスター",
    "ピエロ",
    "カウボーイ",
    "アラビア",
    "古代ギリシャ",
    "アメリカンダイナー",
    "アオザイ",
    "アイドル衣装",
    "スチームパンク",
    "パンクファッション",
    "フラメンコ",
    "水ドレス",
    "骨盤カーテン",
    "肩出し",
    "スーツプロンプト",
    "スパッツ",
    "レギンス",
    "チェック柄",
    "色指定",
    "配色パターン",
    "ネイル",
    "メガネ",
    "スウェット",
    "パーカー",
    "カーディガン",
    "散らかった服",
    "特殊な服",
    "特殊な形状のスカート",
    "大きめの服",
    "女児服",
    "和ロリータ",
    "魔法使いのローブ",
    "女神のプロンプト集",
    "忍者の服",
    "侍のプロンプト",
    "ギャルファッション",
    "店員",
    "防護服",
    "スーツ",
]

POSE_CAT = [
    "ポーズ",
    "構え",
    "座るプロンプト",
    "立ち方",
    "立ちポーズ",
    "立ち絵",
    "歩くポーズ",
    "ジャンプ",
    "四つん這い",
    "前かがみ",
    "跨るポーズ",
    "背中を反らす",
    "M字開脚",
    "2人ポーズ",
    "誘うポーズ",
    "ハグ",
    "キスシーン",
    "カンフー",
    "ヨガ",
    "ストレッチ",
    "ダンス",
    "バレエ",
    "格闘",
    "掴む動作",
    "叩く動作",
    "泳ぎ",
    "バイクに乗る",
    "弓道",
    "銃を持つ",
    "魔法詠唱",
    "入浴",
    "お掃除",
    "タバコ",
    "髪を整える",
    "髪を切る",
    "包帯",
    "くすぐり",
    "縛る",
    "催眠",
    "感電",
    "痙攣",
    "失神",
    "ぐったり",
    "体を密着",
    "床ドン",
    "壁に手",
    "壁に寄りかか",
    "テーブル",
    "手のポーズ",
    "腕のポーズ",
    "脚ポーズ",
    "膝を使った",
    "指ジェスチャー",
    "可愛いポーズ",
    "特殊なポーズ",
    "画像生成AIのポーズ指定",
    "決闘シーン",
    "空を飛ぶ",
    "鏡越し",
    "食べる・舐",
    "アイスを舐める",
    "ガーデニング",
    "体を密着",
    "寝る姿勢",
    "可愛いポーズ",
    "魔法詠唱",
    "銃を",
    "バレーボール",
    "野球部のマネージャー",
    "陸上競技",
    "フィギュア",
    "メガネの種類とポーズ",
    "ジャケットのプロンプト集：種類やポーズ",
    "お尻に関するプロンプト集（サイズとポーズ",
    "胸のプロンプト完全ガイド（形状からポーズ",
    "服のスリット",
    "袖の種類",
]

EXPR_CAT = [
    "表情",
    "口元",
    "よだれ",
    "泣き",
    "恥ずかし",
    "恐怖",
    "快楽",
    "嫌がる",
    "悔し",
    "誘惑",
    "無表情",
    "カメラ目線",
    "視線",
    "息・呼吸",
    "顔文字",
    "感情",
]

CHAR_CAT = [
    "髪型",
    "髪色",
    "前髪",
    "三つ編み",
    "お嬢様ヘア",
    "横髪",
    "ギャルの髪",
    "目元",
    "瞳",
    "血管",
    "うなじ",
    "鎖骨",
    "年齢",
    "体型",
    "胸サイズ",
    "ちびキャラ",
    "SDキャラ",
    "亜人",
    "エルフ",
    "サキュバス",
    "妖精",
    "擬人化",
    "幼い",
    "中学生",
    "子供",
    "大人の女性",
    "イケメン女子",
    "グラマラス",
    "体のパーツ",
    "太もも",
    "お尻",
    "足の裏",
    "足・足指",
    "脇",
    "背中",
    "胸のプロンプト",
    "顔の向き",
    "横顔",
    "顔が見えない",
    "頭頂部",
    "化粧",
    "肌の色",
    "可愛い女の子",
    "美少女",
    "キャバ嬢の髪型",
    "女神",
    "可愛いポーズ・萌え",
    "立ち絵×全身",
    "体に液体",
    "汗ばんだ肌",
    "服や顔の汚れ",
    "風の表現",
    "日焼け",
]

VISUAL_CAT = [
    "構図",
    "アングル",
    "カメラ",
    "ライティング",
    "光のプロンプト",
    "時間帯",
    "エフェクト",
    "シルエット",
    "viewer",
    "ズームレイヤー",
    "背景をぼかす",
    "被写界深度",
    "遠近法",
    "映り込み",
    "反射",
    "陰影",
    "木漏れ日",
    "天井",
    "真下から",
    "部位をアップ",
    "ミーム",
    "雰囲気系",
    "エモい青春",
    "線画",
    "感電エフェクト",
    "見えそうで見えない",
    "覗き見",
    "半分水中",
    "躍動感",
    "Photoshop",
    "ホワイトバランス",
]

PROP_CAT = [
    "椅子",
    "家具",
    "武器",
    "楽器",
    "占い師",
    "ベッドのプロンプト",
    "小物",
    "アイテム",
]

FANTASY_CAT = [
    "亜人種族",
    "ファンタジー世界",
    "侍のプロンプト",
    "魔法使い",
    "鎧のプロンプト",
    "決闘",
]


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


def _any(text: str, keywords: List[str]) -> bool:
    return any(k in text for k in keywords)


def _bg_group(cn: str, gn: str) -> str:
    blob = f"{cn} {gn}"
    if _any(blob, ["教室内", "教室", "学校", "保健室", "体育倉庫", "和室", "部屋", "店内", "電車", "アパート", "ホテルルーム", "キャラの部屋", "ベッド", "室内", "廊下", "玄関", "寝室", "旅館"]):
        return "屋内"
    if _any(blob, ["床", "地面"]):
        return "床"
    if _any(blob, ["都市", "街", "ストリート", "建築", "城", "軍事", "送電", "自販", "群衆", "道", "階段", "オブジェクト"]):
        return "都市"
    if _any(blob, ["壁", "ドア", "窓", "カーテン"]):
        return "屋内"
    return "屋外"


def _cloth_group(cn: str, gn: str) -> str:
    blob = f"{cn} {gn}"
    if _any(blob, ["水着", "スク水", "ビキニ", "スクール水着"]):
        return "水着"
    if _any(blob, ["制服", "スクール", "セーラー", "ブレザー", "学生"]):
        return "制服"
    if _any(blob, ["和服", "浴衣", "振袖", "袴", "巫女", "和ロリ"]):
        return "和服"
    if _any(blob, ["靴下", "タイツ", "パンスト", "ストッキング"]):
        return "靴下"
    if _any(blob, ["靴", "ブーツ", "スニーカー", "パンプス", "サンダル", "足元"]):
        return "靴"
    if _any(blob, ["スカート", "チェック柄"]):
        return "スカート"
    if _any(blob, ["ドレス", "ウェディング", "水ドレス"]):
        return "ドレス"
    if _any(blob, ["コート", "ジャケット", "アウター", "カーディガン", "ポンチョ"]):
        return "コート"
    if _any(blob, ["パンツ", "ズボン", "ショートパンツ", "ボトム"]):
        return "ボトムス"
    if _any(blob, ["シャツ", "Tシャツ", "ブラウス", "トップス", "キャミ"]):
        return "シャツ"
    if _any(blob, ["メイド", "コスプレ", "ナース", "警察", "軍", "ミリタリー", "侍", "忍者", "魔法使い", "シスター", "探偵", "ピエロ", "サンタ", "ハロウィン", "チア", "レースクイーン", "着ぐるみ", "動物コス", "バニー", "巫女", "修道", "カウボーイ", "アラビア", "古代", "アメリカン", "アオザイ", "スチーム", "SF", "近未来", "ファンタジー世界", "原始", "特攻", "防護", "バイクスーツ", "レーシング", "フィギュア", "陸上", "バレー", "野球", "マーチング", "サンバ", "フラメンコ", "レオタード", "体操服", "ブルマ", "エプロン", "はっぴ", "タバード", "腰布", "ふんどし", "ボレロ", "パジャマ", "部屋着"]):
        return "コスチューム・特殊衣装"
    if _any(blob, ["柄", "模様", "配色", "色指定", "チェック", "ストライプ", "ドット"]):
        return "装飾・デザイン"
    if _any(blob, ["素材", "綿", "レース", "サテン", "エナメル", "質感", "網タイツ"]):
        return "素材" if "衣服や装飾品" in blob else "装飾・デザイン"
    if _any(blob, ["リボン", "フリル", "装飾", "襟", "袖", "ネック", "部位名称", "重ね着", "スリット", "はだけ", "破れ", "濡れ", "隙間", "ピチピチ", "肩出し", "骨盤"]):
        return "服の状態・着方"
    if _any(blob, ["ランジェ", "下着", "ブラ", "ガータ", "ペチ", "ショーツ", "スリップ"]):
        return "カジュアル・部屋着"
    if _any(blob, ["メガネ", "帽子", "髪飾", "頭まわり", "アクセサリー", "手袋", "ネイル"]):
        return "アクセサリー・小物"
    if _any(blob, ["民族", "伝統", "チャイナ", "漢服"]):
        return "民族衣装"
    if _any(blob, ["OL", "女子大生", "デート", "カジュアル", "y2k", "ゴシック", "ロリータ", "デコラ", "ヒップホップ", "ストリート", "エモ", "ゆめかわ", "病みかわ", "天使界隈", "姫カジ", "大正", "昭和", "春コーデ", "冬服", "お嬢様", "かっこいい", "豪華", "地味", "ファッション", "コーデ"]):
        return "カジュアル・部屋着"
    return "シャツ"


def _cloth_dest(cn: str, gn: str) -> Dest:
    grp = _cloth_group(cn, gn)
    cat = "衣服や装飾品" if grp in {"素材", "装飾", "パターン", "スタイル"} else "衣装"
    if grp == "素材":
        return ("003_衣装_装飾.yaml", "衣服や装飾品", "素材")
    if grp == "装飾・デザイン":
        return ("003_衣装_装飾.yaml", "衣装", "装飾・デザイン")
    return ("003_衣装_装飾.yaml", cat, grp)


def _pose_group(cn: str, gn: str) -> str:
    blob = f"{cn} {gn}"
    if _any(blob, ["手", "指", "ジェスチャ", "掴", "ハグ", "キス", "舐", "包帯", "髪を整", "髪を切", "タバコ", "銃", "弓道", "詠唱", "掃除", "ガーデニング", "食べ", "酒", "入浴", "洗", "泳", "バイク", "格闘", "カンフー", "ダンス", "バレエ", "ヨガ", "ストレッチ", "ジャンプ", "歩", "座", "立", "跪", "前かがみ", "跨", "四つん", "M字", "壁", "床ドン", "テーブル", "鏡", "催眠", "縛", "拘束", "閉じ込", "くすぐ", "感電", "痙攣", "失神", "ぐったり", "密着", "決闘", "空を飛", "腕", "脚", "膝", "寝る", "背中を反"]):
        if _any(blob, ["手", "指", "ジェスチャ", "掴", "包帯", "髪を整", "髪を切", "タバコ", "銃", "弓道"]):
            return "手の動き・ジェスチャー"
        if _any(blob, ["脚", "M字", "跨", "膝", "四つん"]):
            return "脚の動き・姿勢"
        if _any(blob, ["座", "寝る", "M字"]):
            return "座り・横たわり"
        if _any(blob, ["歩", "ジャンプ", "泳", "ダンス", "バレエ", "バイク", "空を飛"]):
            return "移動・運動"
        if _any(blob, ["格闘", "カンフー", "決闘", "銃"]):
            return "戦闘・格闘"
    return "特殊なポーズ・表現"


def _expr_group(cn: str, gn: str) -> str:
    blob = f"{cn} {gn}"
    if "笑" in blob:
        return "笑"
    if _any(blob, ["泣", "悲"]):
        return "泣き"
    if _any(blob, ["怒", "悔", "嫌"]):
        return "怒り"
    if _any(blob, ["恥", "照"]):
        return "その他表情"
    if _any(blob, ["恐怖", "怯"]):
        return "その他表情"
    if _any(blob, ["誘惑", "快楽", "恍惚"]):
        return "その他表情"
    return "その他表情"


def _nsfw_group(cn: str, gn: str) -> str:
    blob = f"{cn} {gn}".lower()
    if _any(blob, ["ランジェ", "下着", "ブラ", "ガータ", "ショーツ", "スリップ", "透け", "パンティ", "脱ぐ", "隙間", "チラ", "体操服", "ブルマ", "食い込", "透視", "へそ出", "絶対領域", "グラビア", "m字"]):
        return "服"
    if _any(blob, ["快楽", "誘惑", "恍惚", "舐", "キス", "表情"]):
        return "表情・顔"
    if _any(blob, ["ポーズ", "m字", "胸を押", "密着", "くすぐ", "縛", "拘束"]):
        return "動作・ポーズ"
    return "特殊・シチュエーション"


def _group_override(cn: str, gn: str) -> Optional[Dest]:
    blob = f"{cn} {gn}"
    if _any(gn, ["背景", "シーン", "演出", "ステージ", "夜空", "装飾プロンプト", "校内装飾", "イルミネーション", "再現プロンプト", "描写プロンプト", "構築プロンプト", "エントランス", "ルーム", "街", "教室", "保健室", "倉庫", "和室", "部屋", "店内", "電車", "海", "ビーチ", "草原", "植物", "花", "樹木", "天気", "城", "軍事", "道", "階段", "地面", "壁", "ドア", "窓", "観覧", "アパート", "ホテル", "キャンプ", "群衆", "送電", "自販", "破壊", "星空", "火", "水たまり", "都市", "オブジェクト", "ジオラマ", "娯楽", "文化祭", "お花見", "正月", "節分", "ひな", "バレンタイン", "クリスマス", "ハロウィン", "サンタ", "ナイトクラブ", "アイドルのステージ", "ワークスペース", "閉じ込"]):
        if not _any(gn, ["服装", "衣装プロンプト", "服プロンプト", "靴", "手袋", "長靴"]):
            return ("006_背景_環境.yaml", "シーン", _bg_group(cn, gn))
    if _any(gn, ["アイテム", "道具", "武器", "楽器", "家具", "椅子", "ベッド", "小物", "占い", "手に持", "ガーデニング道具"]):
        if _any(gn, ["服装", "服", "靴", "手袋", "長靴", "スニーカー"]):
            return _cloth_dest(cn, gn)
        if "ベッド" in gn and "ポーズ" in cn:
            return ("002_動作_表現.yaml", "基本動作・ポーズ", "座り・横たわり")
        if "ベッド" in gn:
            return ("006_背景_環境.yaml", "シーン", "寝具")
        if "武器" in gn:
            return ("005_小物_道具.yaml", "アイテム", "武器")
        if "楽器" in gn:
            return ("005_小物_道具.yaml", "アイテム", "その他のアイテム")
        if "椅子" in gn or "家具" in gn:
            return ("006_背景_環境.yaml", "シーン", "家具")
        return ("005_小物_道具.yaml", "アイテム", "その他のアイテム")
    if _any(gn, ["ポーズ", "構え", "仕草", "動作", "座", "立", "歩", "踊", "ダンス", "バレエ", "ヨガ", "ストレッチ", "ジャンプ", "四つん", "前かがみ", "跨", "手", "腕", "脚", "膝", "ハグ", "キス", "掴", "叩", "格闘", "泳", "入浴", "掃除", "タバコ", "髪を整", "髪を切", "包帯", "催眠", "縛", "拘束", "銃", "弓道", "詠唱", "バイク", "逮捕", "視線", "カメラ目線"]):
        if _any(gn, ["表情"]):
            return ("002_動作_表現.yaml", "表情動作", _expr_group(cn, gn))
        return ("002_動作_表現.yaml", "基本動作・ポーズ", _pose_group(cn, gn))
    if _any(gn, ["表情", "口元", "よだれ", "泣", "恥", "恐怖", "快楽", "嫌", "悔", "誘惑", "無表情", "息", "呼吸"]):
        return ("002_動作_表現.yaml", "表情動作", _expr_group(cn, gn))
    if _any(gn, ["服装", "衣装", "服", "靴", "スカート", "ドレス", "シャツ", "コート", "水着", "制服", "和服", "リボン", "フリル", "柄", "素材", "襟", "袖", "ブラ", "ガータ", "ランジェ", "下着", "パジャマ", "タイツ", "靴下", "装飾", "ネック", "メガネ", "帽子", "アクセサリー", "手袋"]):
        return _cloth_dest(cn, gn)
    if _any(gn, ["髪", "目", "瞳", "眉", "肌", "体型", "胸", "年齢", "亜人", "種族"]):
        return _char_dest(cn, gn)
    if _any(gn, ["構図", "アングル", "カメラ", "ライト", "光", "エフェクト", "シルエット", "ぼか", "フォーカス", "ズーム", "反射", "映り込", "遠近", "viewer", "雰囲気", "線画"]):
        return _visual_dest(cn, gn)
    return None


def _char_dest(cn: str, gn: str) -> Dest:
    blob = f"{cn} {gn}"
    if _any(blob, ["髪色", "カラー", "メッシュ"]):
        return ("001_キャラクター.yaml", "髪パーツ", "髪の色")
    if _any(blob, ["髪型", "ヘア", "三つ編", "前髪", "横髪", "ポニー", "お嬢様ヘア", "ギャル"]):
        return ("001_キャラクター.yaml", "髪パーツ", "特殊な髪型")
    if _any(blob, ["目", "瞳", "まつ毛", "眉毛"]):
        return ("001_キャラクター.yaml", "顔パーツ", "目の形状")
    if _any(cn, ["口元"]) or "唇" in blob:
        return ("001_キャラクター.yaml", "顔パーツ", "唇")
    if _any(blob, ["肌", "化粧", "メイク", "日焼", "汗"]):
        return ("001_キャラクター.yaml", "人物", "皮膚")
    if _any(blob, ["胸", "お尻", "太もも", "足", "脇", "背中", "鎖骨", "うなじ", "血管", "肩", "体のパーツ", "部位"]):
        return ("001_キャラクター.yaml", "身体パーツ", "胸部")
    if _any(blob, ["年齢", "中学生", "子供", "幼", "大人", "ちび", "SDキャラ"]):
        return ("001_キャラクター.yaml", "人物", "年齢")
    if _any(blob, ["体型", "グラマラス", "くびれ", "胸サイズ"]):
        return ("001_キャラクター.yaml", "人物", "体型")
    if _any(blob, ["亜人", "エルフ", "サキュバス", "妖精", "擬人化", "女神"]):
        return ("008_ジャンル_世界観.yaml", "ファンタジー", "亜人・種族")
    if _any(blob, ["顔の向き", "横顔", "顔が見えない", "頭頂", "つむじ"]):
        return ("001_キャラクター.yaml", "人物", "顔の形")
    if _any(blob, ["イケメン女子", "可愛い女", "美少女"]):
        return ("001_キャラクター.yaml", "人物", "キャラクター")
    return ("001_キャラクター.yaml", "人物", "キャラクター")


def _visual_dest(cn: str, gn: str) -> Dest:
    blob = f"{cn} {gn}"
    if _any(blob, ["線画", "スケッチ", "Photoshop", "画風"]):
        return ("004_視覚効果.yaml", "画面", "スケッチ")
    if _any(blob, ["構図", "フレーミング", "見えそう", "覗き", "半分水中", "立ち絵", "全身"]):
        return ("004_視覚効果.yaml", "アングル・構図", "特殊な構図")
    if _any(blob, ["アングル", "カメラ", "視点", "真下", "天井", "横顔構図", "viewer", "ズーム", "レンズ", "ぼか", "被写界深度", "フォーカス", "部位をアップ", "アップ"]):
        if _any(blob, ["ライト", "光", "時間帯", "陰影", "木漏れ日", "ネオン"]):
            return ("004_視覚効果.yaml", "アングル・構図", "ライティング")
        if _any(blob, ["レンズ", "ぼか", "被写界深度"]):
            return ("004_視覚効果.yaml", "アングル・構図", "レンズ・効果")
        return ("004_視覚効果.yaml", "アングル・構図", "視点・角度")
    if _any(blob, ["ライト", "光", "時間帯", "陰影", "木漏れ日", "ネオン", "エモい"]):
        return ("004_視覚効果.yaml", "アングル・構図", "ライティング")
    if _any(blob, ["色", "カラー", "ネオン"]):
        return ("004_視覚効果.yaml", "色・色彩", "基本色")
    if _any(blob, ["エフェクト", "感電", "ミーム", "雰囲気", "シルエット", "ダブルエクスポージャー", "躍動", "風", "映り込", "反射", "遠近"]):
        return ("004_視覚効果.yaml", "画面", "芸術スタイル")
    if _any(blob, ["視線", "カメラ目線"]):
        return ("004_視覚効果.yaml", "アングル・構図", "視線")
    return ("004_視覚効果.yaml", "アングル・構図", "視点・角度")


def _map_dest(cat_name: str, group_name: str, tag: str) -> Dest:
    cn, gn = cat_name or "", group_name or ""
    blob = f"{cn} {gn}"

    override = _group_override(cn, gn)
    if override:
        return override

    if _any(cn, NSFW_CAT):
        return ("009_NSFW.yaml", "NSFW", _nsfw_group(cn, gn))

    if _any(cn, FOOD_CAT):
        return ("007_食べ物.yaml", "食べ物・飲み物", "食べ物・飲み物")

    if _any(cn, BG_CAT):
        if _any(cn, ["植物", "花", "樹木"]):
            return ("006_背景_環境.yaml", "植物・自然", "植物")
        if _any(cn, ["天気", "星空", "火・炎", "水たまり", "時間帯"]):
            return ("006_背景_環境.yaml", "背景", "天候・時間帯")
        if _any(cn, ["壁", "ドア", "窓", "床", "地面", "建築", "階段", "道", "オブジェクト"]):
            return ("006_背景_環境.yaml", "背景", "都市・建物")
        return ("006_背景_環境.yaml", "シーン", _bg_group(cn, gn))

    if _any(cn, PROP_CAT):
        if "武器" in cn:
            return ("005_小物_道具.yaml", "アイテム", "武器")
        if "楽器" in cn:
            return ("005_小物_道具.yaml", "アイテム", "その他のアイテム")
        if "椅子" in cn or "家具" in cn:
            return ("006_背景_環境.yaml", "シーン", "家具")
        return ("005_小物_道具.yaml", "アイテム", "その他のアイテム")

    if _any(cn, VISUAL_CAT):
        return _visual_dest(cn, gn)

    if _any(cn, EXPR_CAT):
        return ("002_動作_表現.yaml", "表情動作", _expr_group(cn, gn))

    if _any(cn, POSE_CAT):
        if _any(cn, ["キス", "舐", "快楽", "誘惑", "M字", "グラビア", "脱ぐ", "透け", "隙間", "胸を押"]):
            return ("009_NSFW.yaml", "NSFW", _nsfw_group(cn, gn))
        return ("002_動作_表現.yaml", "基本動作・ポーズ", _pose_group(cn, gn))

    if "服や顔の汚れ" in cn:
        return ("003_衣装_装飾.yaml", "衣装", "服の状態・着方")

    if _any(cn, CHAR_CAT):
        return _char_dest(cn, gn)

    if _any(cn, FANTASY_CAT):
        if "鎧" in cn or "甲冑" in cn:
            return ("003_衣装_装飾.yaml", "衣服や装飾品", "よろい")
        return ("008_ジャンル_世界観.yaml", "ファンタジー", "亜人・種族")

    if _any(cn, CLOTHING_CAT):
        if _any(cn, ["透け", "脱ぐ", "隙間", "チラ", "ランジェ", "下着デザイン", "パンティ", "体操服×", "グラビア", "M字", "絶対領域"]):
            return ("009_NSFW.yaml", "NSFW", _nsfw_group(cn, gn))
        return _cloth_dest(cn, gn)

    if "線画" in cn:
        return ("004_視覚効果.yaml", "画面", "スケッチ")

    if "Photoshop" in cn or "ホワイトバランス" in cn:
        return ("000_画像品質_技術.yaml", "クオリティ", "品質・解像度")

    # tag-level fallback
    t = (tag or "").lower()
    if re.search(r"(swimsuit|bikini|school_uniform|dress|skirt|shirt|coat|jacket|pants|shoes|boots|socks|kimono|maid|lingerie|underwear|bra|panties)", t):
        return _cloth_dest(cn, gn)
    if re.search(r"(pose|standing|sitting|walking|running|dancing|hug|kiss|sleeping|jumping|stretching)", t):
        return ("002_動作_表現.yaml", "基本動作・ポーズ", _pose_group(cn, gn))
    if re.search(r"(smile|cry|blush|angry|scared|expression|open_mouth|closed_eyes)", t):
        return ("002_動作_表現.yaml", "表情動作", _expr_group(cn, gn))
    if re.search(r"(background|outdoors|indoors|classroom|bedroom|street|city|forest|beach|sky|night|sunset|rain|snow)", t):
        return ("006_背景_環境.yaml", "シーン", _bg_group(cn, gn))
    if re.search(r"(sword|gun|weapon|chair|table|bed|instrument|guitar|piano)", t):
        if "bed" in t:
            return ("006_背景_環境.yaml", "シーン", "寝具")
        if re.search(r"(sword|gun|weapon)", t):
            return ("005_小物_道具.yaml", "アイテム", "武器")
        return ("005_小物_道具.yaml", "アイテム", "その他のアイテム")

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
        stats["errors"] = stats["errors"][:30]
        stats["error_count"] = len(stats["errors"])
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
        }
        with open(os.path.join(group_tags_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        with open(os.path.join(group_tags_dir, "search-index.pkl"), "wb") as f:
            pickle.dump(search_index, f)

    return stats


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    result = merge(dry_run=dry)
    print(json.dumps(result, ensure_ascii=False, indent=2))
