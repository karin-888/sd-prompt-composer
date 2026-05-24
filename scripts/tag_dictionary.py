""" -*- coding: UTF-8 -*-
Tag dictionary loader for Prompt Composer.

Reads tags from prompt-aio's YAML file and exposes a simple
in-memory search API for the FastAPI routes.
"""

import os
import urllib.parse
from typing import List, Dict, Optional

import yaml

import user_storage
import tag_text_utils
import preview_filenames

_tags: List[Dict] = []
_loaded: bool = False
_jp_map: Dict[str, str] = {}
_extension_dir: str = ""
_previews_dir: str = ""
_preview_by_tag: Dict[str, str] = {}
_preview_dir_mtime: float = 0.0
_related_preview_cache: Dict[str, Optional[str]] = {}
_preview_alias_index: Dict[str, str] = {}
_PREVIEW_EXTS = (".webp", ".png", ".jpg", ".jpeg", ".gif")


def _tag_dedupe_key(tag: str) -> str:
    return (tag or "").strip().lower()


def _item_dedupe_score(item: Dict) -> int:
    tag = (item.get("tag") or "").strip()
    score = 0
    if _resolve_preview_path(tag, (item.get("preview") or "").strip(), allow_related=False):
        score += 1000
    elif tag in _preview_by_tag:
        score += 1000
    if (item.get("preview") or "").strip():
        score += 500
    score += min(len((item.get("jp") or "").strip()), 200)
    return score


def _dedupe_items(items: List[Dict]) -> List[Dict]:
    """Keep one entry per tag string (case-insensitive), preferring preview + richer jp."""
    best: Dict[str, tuple[int, int]] = {}
    for idx, item in enumerate(items):
        key = _tag_dedupe_key(item.get("tag") or "")
        if not key:
            continue
        score = _item_dedupe_score(item)
        prev = best.get(key)
        if prev is None or score > prev[0] or (score == prev[0] and idx < prev[1]):
            best[key] = (score, idx)

    keep_indices = {idx for _score, idx in best.values()}
    return [item for idx, item in enumerate(items) if idx in keep_indices]


def _parse_yaml_sections(data) -> List[Dict]:
    items: List[Dict] = []
    if not isinstance(data, list):
        return items

    for section in data:
        section_name = section.get("name") or ""
        for cat in section.get("categories", []) or []:
            cat_name = cat.get("name") or ""
            for group in cat.get("groups", []) or []:
                group_name = group.get("name") or ""
                tags = group.get("tags", {}) or {}
                for key, value in tags.items():
                    eng = str(key)
                    preview_name = ""
                    if isinstance(value, dict):
                        jp_text = str(value.get("jp") or value.get("label") or "")
                        preview_name = str(value.get("preview") or "").strip()
                    else:
                        jp_text = str(value) if value is not None else ""
                    eng, jp_text = tag_text_utils.normalize_tag_jp(eng, jp_text)
                    item = {
                        "tag": eng,
                        "jp": jp_text,
                        "section": section_name,
                        "category": cat_name,
                        "group": group_name,
                    }
                    if preview_name:
                        item["preview"] = preview_name
                    items.append(item)
    return items


def _dictionary_yaml_paths(extension_dir: str) -> List[str]:
    paths: List[str] = []
    local_yaml_path = os.path.join(extension_dir, "group_tags", "default.yaml")
    if os.path.isfile(local_yaml_path):
        paths.append(local_yaml_path)

    group_dir = os.path.join(extension_dir, "group_tags")
    if os.path.isdir(group_dir):
        for name in sorted(os.listdir(group_dir)):
            if not name.endswith(".yaml") or name == "default.yaml":
                continue
            path = os.path.join(group_dir, name)
            if os.path.isfile(path) and path not in paths:
                paths.append(path)

    if paths:
        return paths

    base_path = os.path.dirname(os.path.dirname(extension_dir))
    fallback_yaml_path = os.path.join(
        base_path, "extensions", "sd-webui-prompt-aio-enhanced", "group_tags", "default.yaml"
    )
    if os.path.isfile(fallback_yaml_path):
        paths.append(fallback_yaml_path)
    return paths


def init(extension_dir: str):
    """Load tag dictionary once at startup."""
    global _tags, _loaded, _jp_map, _extension_dir, _previews_dir
    if _loaded:
        return

    _extension_dir = extension_dir
    _previews_dir = user_storage.tag_previews_dir(extension_dir)

    yaml_paths = _dictionary_yaml_paths(extension_dir)
    if not yaml_paths:
        print("[Prompt Composer] Tag dictionary YAML not found")
        _tags = []
        _loaded = True
        _scan_previews(force=True)
        return

    items: List[Dict] = []
    loaded_files: List[str] = []
    for yaml_path in yaml_paths:
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception as e:
            print(f"[Prompt Composer] Failed to load tag dictionary {yaml_path}: {e}")
            continue
        items.extend(_parse_yaml_sections(data))
        loaded_files.append(os.path.basename(yaml_path))

    _scan_previews(force=True)
    before = len(items)
    items = _dedupe_items(items)
    removed = before - len(items)
    _tags = items
    _jp_map = {}
    for it in _tags:
        tag = (it.get("tag") or "").strip()
        jp = (it.get("jp") or "").strip()
        if tag and jp and tag not in _jp_map:
            _jp_map[tag] = jp
    _loaded = True
    dup_note = f", deduped={removed}" if removed else ""
    print(
        f"[Prompt Composer] Loaded {len(_tags)} prompt dictionary tags "
        f"from {', '.join(loaded_files)} (previews={len(_preview_by_tag)}{dup_note})"
    )


def previews_dir() -> str:
    return _previews_dir


def _rebuild_preview_alias_index() -> None:
    global _preview_alias_index
    index: Dict[str, tuple[str, str]] = {}

    def add_alias(alias: str, known_tag: str, path: str) -> None:
        alias = alias.strip().lower()
        if len(alias) < 3:
            return
        prev = index.get(alias)
        if prev is None or len(known_tag) < len(prev[0]):
            index[alias] = (known_tag, path)

    for known_tag, path in _preview_by_tag.items():
        kt = known_tag.strip()
        add_alias(kt, kt, path)
        first = kt.split(",", 1)[0].strip()
        add_alias(first, kt, path)
        for part in kt.split(","):
            part = part.strip()
            add_alias(part, kt, path)
            if part.startswith("(") and ":" in part:
                add_alias(part.split(":", 1)[0][1:].strip(), kt, path)

    _preview_alias_index = {alias: path for alias, (_known, path) in index.items()}


def _scan_previews(force: bool = False) -> None:
    global _preview_by_tag, _preview_dir_mtime, _related_preview_cache, _preview_alias_index
    if not _previews_dir or not os.path.isdir(_previews_dir):
        _preview_by_tag = {}
        _preview_dir_mtime = 0.0
        return

    try:
        mtime = os.path.getmtime(_previews_dir)
    except OSError:
        mtime = 0.0
    if not force and mtime == _preview_dir_mtime:
        return

    try:
        found = preview_filenames.scan_previews(_previews_dir)
    except OSError:
        found = {}

    _preview_by_tag = found
    _preview_dir_mtime = mtime
    _related_preview_cache = {}
    _rebuild_preview_alias_index()


def _tags_related_for_preview(query: str, candidate: str) -> bool:
    """True when query can reuse candidate's preview (e.g. table variant -> card tag)."""
    q = (query or "").strip().lower()
    c = (candidate or "").strip().lower()
    if not q or not c:
        return False
    if q == c:
        return True
    q_first = q.split(",", 1)[0].strip()
    c_first = c.split(",", 1)[0].strip()
    if q_first == c or q_first == c_first:
        return True
    if q.startswith(c + ",") or q.startswith(c + " "):
        return True
    if c.startswith(q + ",") or c.startswith(q + " "):
        return True
    if f", {q}," in c or c.endswith(f", {q}") or f"({q}" in c or f"({q}:" in c:
        return True
    return False


def _find_related_preview_path(tag: str) -> Optional[str]:
    tag = (tag or "").strip()
    if not tag or not _preview_by_tag:
        return None
    if tag in _related_preview_cache:
        return _related_preview_cache[tag]

    alias_hit = _preview_alias_index.get(tag.lower())
    _related_preview_cache[tag] = alias_hit
    return alias_hit


def _resolve_preview_path(tag: str, yaml_preview: str = "", *, allow_related: bool = True) -> Optional[str]:
    _scan_previews()
    tag = (tag or "").strip()
    if not tag:
        return None

    if yaml_preview:
        preview = yaml_preview.strip()
        if os.path.isabs(preview):
            return preview if os.path.isfile(preview) else None
        direct = os.path.join(_previews_dir, preview)
        if os.path.isfile(direct):
            return direct
        stem = os.path.splitext(preview)[0]
        for ext in _PREVIEW_EXTS:
            candidate = os.path.join(_previews_dir, stem + ext)
            if os.path.isfile(candidate):
                return candidate

    hit = _preview_by_tag.get(tag)
    if hit:
        return hit

    safe_base = preview_filenames.tag_to_preview_basename(tag)
    for ext in _PREVIEW_EXTS:
        candidate = os.path.join(_previews_dir, safe_base + ext)
        if os.path.isfile(candidate):
            return candidate

    if "," in tag and allow_related:
        first = tag.split(",", 1)[0].strip()
        if first and first != tag:
            path = _resolve_preview_path(first, yaml_preview, allow_related=False)
            if path:
                return path

    return _find_related_preview_path(tag) if allow_related else None


def preview_url_for_tag(tag: str, yaml_preview: str = "") -> Optional[str]:
    path = _resolve_preview_path(tag, yaml_preview)
    if not path:
        return None
    encoded_tag = urllib.parse.quote(tag or "", safe="")
    return f"/prompt-composer/api/tags/preview?tag={encoded_tag}"


def get_preview_file(tag: str) -> Optional[str]:
    item = next((it for it in _tags if (it.get("tag") or "") == tag), None)
    yaml_preview = (item or {}).get("preview") or ""
    return _resolve_preview_path(tag, yaml_preview)


def rescan_previews() -> int:
    _scan_previews(force=True)
    return len(_preview_by_tag)


def _public_item(item: Dict) -> Dict:
    out = dict(item)
    yaml_preview = (item.get("preview") or "").strip()
    url = preview_url_for_tag(item.get("tag") or "", yaml_preview)
    out["previewUrl"] = url
    return out


def translate_exact(tag: str) -> str:
    """Return JP translation for exact tag if present in dictionary YAML."""
    if not _loaded:
        return ""
    t = (tag or "").strip()
    if not t:
        return ""
    return (_jp_map.get(t) or "").strip()


def search_tags(
    query: str = "",
    limit: int = 50,
    section: str | None = None,
    category: str | None = None,
    group: str | None = None,
) -> List[Dict]:
    """Simple case-insensitive search over english tag and jp text, with optional path filters."""
    if not _loaded:
        return []

    q = (query or "").strip().lower()

    def match_path(item: Dict) -> bool:
        if section and item["section"] != section:
            return False
        if category and item["category"] != category:
            return False
        if group and item["group"] != group:
            return False
        return True

    results: List[Dict] = []
    for item in _tags:
        if len(results) >= limit:
            break
        if not match_path(item):
            continue
        if not q or q in item["tag"].lower() or q in item["jp"].lower():
            results.append(_public_item(item))

    # If we filtered everything out with path, but no query, try again without path to provide something
    if not results and not q and not any([section, category, group]):
        return [_public_item(it) for it in _tags[: max(1, min(limit, 200))]]

    return results


def list_paths() -> List[Dict]:
    """Return distinct (section, category, group) combinations."""
    if not _loaded:
        return []

    seen = set()
    paths: List[Dict] = []
    for item in _tags:
        key = (item["section"], item["category"], item["group"])
        if key in seen:
            continue
        seen.add(key)
        paths.append(
            {
                "section": item["section"],
                "category": item["category"],
                "group": item["group"],
            }
        )
    return paths


def _path_key(section: str, category: str = "", group: str = "") -> str:
    """Build a UI tree path key (matches javascript/tags.js)."""
    sec = (section or "").strip() or "(未分類)"
    cat = (category or "").strip()
    grp = (group or "").strip()
    parts = [sec]
    if cat:
        parts.append(cat)
        if grp:
            parts.append(grp)
    return "/".join(parts)


def path_tag_counts() -> Dict[str, int]:
    """Return tag counts for each folder node in the path tree."""
    if not _loaded:
        return {}

    counts: Dict[str, int] = {}
    for item in _tags:
        sec = item.get("section") or ""
        cat = item.get("category") or ""
        grp = item.get("group") or ""
        keys = [_path_key(sec)]
        if (cat or "").strip():
            keys.append(_path_key(sec, cat))
            if (grp or "").strip():
                keys.append(_path_key(sec, cat, grp))
        for key in keys:
            counts[key] = counts.get(key, 0) + 1
    return counts
