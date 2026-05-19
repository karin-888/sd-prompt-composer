# -*- coding: UTF-8 -*-
"""Load Infinite Prompt Studio tag/preset data from ips_data/*.js (no Node required)."""

import os
import re
from typing import Any, Dict, List, Optional, Tuple

_DATA_DIR: Optional[str] = None
_cache_mtime: float = 0.0
_cache: Dict[str, Any] = {}

FASHION_FILE = "fashion_presets.js"
SKIP_TAG_FILES = {FASHION_FILE, "config_presets.js", "controlnet_model_list.js"}

OUTFIT_SLOTS = ("inner", "bra", "pants", "top", "outer", "bottom", "socks", "shoes", "acc")
COLOR_SUFFIXES = ("C", "M", "Q")

GENRE_LABELS: Dict[str, str] = {
    "gyaru": "ギャル",
    "miko": "巫女服",
    "school": "制服",
    "maid": "メイド服",
    "dress": "ドレス",
    "goth": "ゴスロリ",
    "rpg": "ファンタジー",
    "wafuku": "和服",
    "china": "チャイナ / 中華服",
    "idol": "アイドル衣装",
    "casual": "カジュアル",
    "swimsuit": "水着",
    "cosplay": "コスプレ",
    "mecha": "メカ少女 / 武装少女",
    "occupation": "職業制服",
    "nurse": "ナース服",
    "nun": "シスター服",
    "ol": "OL・事務服",
    "princess": "お姫様ドレス",
    "jirai": "地雷系・量産型",
    "shibuya": "ストリート系",
    "r18": "R18",
    "r15": "R15",
}

# Default PC block type when inserting a tag from a module
MODULE_BLOCK: Dict[str, str] = {
    "common_poses": "composition",
    "data_poses": "composition",
    "data_common": "character",
    "data_character": "character",
    "data_expressions": "expression",
    "data_quality": "quality",
    "data_backgrounds": "background",
    "data_lighting": "lighting",
    "data_camera": "composition",
    "data_angles": "composition",
    "data_compositions": "composition",
    "data_modifiers": "style",
    "data_colors": "appearance",
    "data_r18": "composition",
    "data_r15": "composition",
}

FIELD_RE = re.compile(r'\b([a-zA-Z]+)\s*:\s*"((?:[^"\\]|\\.)*)"')


def init(extension_dir: str) -> None:
    global _DATA_DIR
    local = os.path.join(extension_dir, "ips_data")
    if os.path.isdir(local):
        _DATA_DIR = os.path.realpath(local)
        return
    fallback = os.path.join(
        extension_dir,
        "..",
        "infinite-prompt-studio",
        "app",
        "data",
    )
    fallback = os.path.realpath(fallback)
    _DATA_DIR = fallback if os.path.isdir(fallback) else local


def data_dir() -> Optional[str]:
    return _DATA_DIR


def is_available() -> bool:
    return bool(_DATA_DIR and os.path.isdir(_DATA_DIR))


def _dir_mtime() -> float:
    if not _DATA_DIR or not os.path.isdir(_DATA_DIR):
        return 0.0
    try:
        mtimes = [os.path.getmtime(os.path.join(_DATA_DIR, f)) for f in os.listdir(_DATA_DIR) if f.endswith(".js")]
        return max(mtimes) if mtimes else 0.0
    except OSError:
        return 0.0


def _ensure_loaded() -> None:
    global _cache, _cache_mtime
    mtime = _dir_mtime()
    if _cache and mtime == _cache_mtime:
        return
    _cache_mtime = mtime
    _cache = {
        "modules": _load_modules(),
        "fashion": _load_fashion_presets(),
    }


def _read_js(name: str) -> str:
    path = os.path.join(_DATA_DIR or "", name)
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _module_label(stem: str, text: str) -> str:
    m = re.search(r"//\s*(?:data/)?[\w.]+\s*[-–—:]\s*(.+)", text)
    if m:
        return m.group(1).strip()[:80]
    return stem.replace("_", " ").replace("data ", "")


def _default_block(stem: str) -> str:
    if stem in MODULE_BLOCK:
        return MODULE_BLOCK[stem]
    if "pose" in stem or "camera" in stem or "angle" in stem or "composition" in stem:
        return "composition"
    if "background" in stem:
        return "background"
    if "light" in stem:
        return "lighting"
    if "quality" in stem:
        return "quality"
    if "expression" in stem:
        return "expression"
    if "outfit" in stem or "fashion" in stem or stem.startswith("data_"):
        if any(x in stem for x in ("school", "maid", "gyaru", "swimsuit", "cosplay", "dress", "goth")):
            return "outfit"
    return "character"


def _parse_fields(block: str) -> Dict[str, str]:
    return {m.group(1): m.group(2) for m in FIELD_RE.finditer(block)}


def _extract_brace_objects(section: str) -> List[str]:
    objects: List[str] = []
    i = 0
    n = len(section)
    while i < n:
        if section[i] != "{":
            i += 1
            continue
        depth = 0
        start = i
        j = i
        while j < n:
            c = section[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    objects.append(section[start + 1 : j])
                    i = j + 1
                    break
            j += 1
        else:
            break
    return objects


def _parse_lt_tags(text: str) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    seen = set()
    for block in _extract_brace_objects(text):
        if "l:" not in block or "t:" not in block:
            continue
        if "top:" in block and "t:" in block:
            # fashion preset objects also have l + top; skip if no t before top heuristic
            fields = _parse_fields("{" + block + "}")
            if "top" in fields and "t" not in fields:
                continue
        fields = _parse_fields("{" + block + "}")
        label = fields.get("l", "").strip()
        tag = fields.get("t", "").strip()
        if not label or not tag:
            continue
        cat = fields.get("cat", "").strip()
        key = (label, tag, cat)
        if key in seen:
            continue
        seen.add(key)
        items.append({"l": label, "t": tag, "cat": cat})
    return items


def _load_modules() -> List[Dict[str, Any]]:
    modules: List[Dict[str, Any]] = []
    if not is_available():
        return modules
    for name in sorted(os.listdir(_DATA_DIR or "")):
        if not name.endswith(".js") or name in SKIP_TAG_FILES:
            continue
        stem = name[:-3]
        text = _read_js(name)
        if not text:
            continue
        tags = _parse_lt_tags(text)
        if not tags:
            continue
        cats = sorted({t["cat"] for t in tags if t.get("cat")})
        modules.append(
            {
                "id": stem,
                "file": name,
                "label": _module_label(stem, text),
                "block": _default_block(stem),
                "tagCount": len(tags),
                "categories": cats,
                "tags": tags,
            }
        )
    return modules


def preset_to_prompt(preset: Dict[str, str]) -> str:
    parts: List[str] = []
    for slot in OUTFIT_SLOTS:
        val = (preset.get(slot) or "").strip()
        if not val or val.lower() == "none":
            continue
        chunk: List[str] = []
        for suffix in COLOR_SUFFIXES:
            ck = slot + suffix
            cv = (preset.get(ck) or "").strip()
            if cv and cv.lower() != "none":
                chunk.append(cv)
        chunk.append(val)
        parts.append(" ".join(chunk))
    return ", ".join(parts)


def _load_fashion_presets() -> Dict[str, List[Dict[str, Any]]]:
    text = _read_js(FASHION_FILE)
    if not text:
        return {}
    start = text.find("{", text.find("FASHION_PRESETS"))
    if start < 0:
        return {}
    body = text[start:]
    genre_starts = list(re.finditer(r"\n\s*([a-zA-Z0-9_]+)\s*:\s*\[", body))
    genres: Dict[str, List[Dict[str, Any]]] = {}
    for i, m in enumerate(genre_starts):
        genre = m.group(1)
        sec_start = m.end()
        sec_end = genre_starts[i + 1].start() if i + 1 < len(genre_starts) else len(body)
        section = body[sec_start:sec_end]
        presets: List[Dict[str, Any]] = []
        for block in _extract_brace_objects(section):
            fields = _parse_fields("{" + block + "}")
            if "l" not in fields or "top" not in fields:
                continue
            prompt = preset_to_prompt(fields)
            presets.append(
                {
                    "label": fields.get("l", ""),
                    "prompt": prompt,
                    "fields": fields,
                }
            )
        if presets:
            genres[genre] = presets
    return genres


def get_status() -> Dict[str, Any]:
    _ensure_loaded()
    modules = _cache.get("modules") or []
    fashion = _cache.get("fashion") or {}
    return {
        "available": is_available(),
        "dataDir": _DATA_DIR or "",
        "moduleCount": len(modules),
        "fashionGenreCount": len(fashion),
        "tagCount": sum(m.get("tagCount", 0) for m in modules),
    }


def list_modules() -> List[Dict[str, Any]]:
    _ensure_loaded()
    return [
        {
            "id": m["id"],
            "label": m["label"],
            "block": m["block"],
            "tagCount": m["tagCount"],
            "categories": m.get("categories") or [],
        }
        for m in (_cache.get("modules") or [])
    ]


def search_module_tags(
    module_id: str,
    q: str = "",
    cat: Optional[str] = None,
    limit: int = 120,
) -> List[Dict[str, str]]:
    _ensure_loaded()
    mod = next((m for m in (_cache.get("modules") or []) if m["id"] == module_id), None)
    if not mod:
        return []
    items = mod.get("tags") or []
    qq = (q or "").strip().lower()
    if cat:
        items = [t for t in items if (t.get("cat") or "") == cat]
    if qq:
        items = [
            t
            for t in items
            if qq in t.get("l", "").lower() or qq in t.get("t", "").lower()
        ]
    return items[: max(1, min(limit, 500))]


def list_fashion_genres() -> List[Dict[str, str]]:
    _ensure_loaded()
    fashion = _cache.get("fashion") or {}
    out: List[Dict[str, str]] = []
    for gid in sorted(fashion.keys()):
        out.append({"id": gid, "label": GENRE_LABELS.get(gid, gid), "count": len(fashion[gid])})
    return out


def list_fashion_presets(genre: str, q: str = "", limit: int = 80) -> List[Dict[str, Any]]:
    _ensure_loaded()
    fashion = _cache.get("fashion") or {}
    items = fashion.get(genre) or []
    qq = (q or "").strip().lower()
    if qq:
        items = [
            p
            for p in items
            if qq in (p.get("label") or "").lower() or qq in (p.get("prompt") or "").lower()
        ]
    lim = max(1, min(limit, 200))
    return [
        {"label": p["label"], "prompt": p["prompt"]}
        for p in items[:lim]
    ]


def get_fashion_preset(genre: str, index: int) -> Optional[Dict[str, Any]]:
    _ensure_loaded()
    fashion = _cache.get("fashion") or {}
    items = fashion.get(genre) or []
    if index < 0 or index >= len(items):
        return None
    p = items[index]
    return {"label": p["label"], "prompt": p["prompt"], "genre": genre}
