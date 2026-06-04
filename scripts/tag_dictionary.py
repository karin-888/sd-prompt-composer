""" -*- coding: UTF-8 -*-
Tag dictionary loader for Prompt Composer.

When ``group_tags/manifest.json`` exists, sections are loaded on demand from
``group_tags/sections/*.yaml``. Otherwise falls back to loading legacy YAML files.
"""

import json
import os
import pickle
import threading
import time
import urllib.parse
from typing import List, Dict, Optional, Tuple, Set

import yaml

import user_storage
import tag_text_utils
import preview_filenames

_tags: List[Dict] = []
_loaded: bool = False
_lazy_mode: bool = False
_jp_map: Dict[str, str] = {}
_extension_dir: str = ""
_previews_dir: str = ""
_preview_by_tag: Dict[str, str] = {}
_preview_dir_mtime: float = 0.0
_related_preview_cache: Dict[str, Optional[str]] = {}
_preview_alias_index: Dict[str, str] = {}
_tag_by_name: Dict[str, Dict] = {}
_tags_by_path: Dict[Tuple[str, str, str], List[int]] = {}
_cached_paths: List[Dict] = []
_cached_path_counts: Dict[str, int] = {}
_cached_path_entries: List[Dict] = []
_manifest_sections: Dict[str, Dict] = {}
_manifest_sections_ordered: List[Dict] = []
_search_index: List[Dict] = []
_loaded_sections: Set[str] = set()
_global_tag_keys: Set[str] = set()
_previews_scanned: bool = False
_preview_scan_lock = threading.Lock()
_preview_scan_started: bool = False
_MANIFEST_VERSION = 2
_SECTION_CACHE_VERSION = 2
_LEGACY_CACHE_VERSION = 1
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
    jp = (item.get("jp") or "").strip()
    if jp and not tag_text_utils.is_low_quality_jp(tag, jp):
        score += min(len(jp), 200)
    return score


def _resolve_jp_labels(items: List[Dict]) -> None:
    lookup = tag_text_utils.build_jp_lookup(items)
    for item in items:
        tag = (item.get("tag") or "").strip()
        item["jp"] = tag_text_utils.resolve_jp_label(tag, item.get("jp") or "", lookup)


def _dedupe_items(items: List[Dict]) -> List[Dict]:
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
        if not isinstance(section, dict):
            continue
        section_name = section.get("name") or ""
        for cat in section.get("categories", []) or []:
            if not isinstance(cat, dict):
                continue
            cat_name = cat.get("name") or ""
            for group in cat.get("groups", []) or []:
                if not isinstance(group, dict):
                    continue
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
                    jp_text = tag_text_utils.sanitize_tag_jp(eng, jp_text)
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


_PATH_SEP = "\x1f"


def _path_key(section: str, category: str = "", group: str = "") -> str:
    sec = (section or "").strip() or "(未分類)"
    cat = (category or "").strip()
    grp = (group or "").strip()
    parts = [sec]
    if cat:
        parts.append(cat)
        if grp:
            parts.append(grp)
    return _PATH_SEP.join(parts)


def _group_tags_dir() -> str:
    return os.path.join(_extension_dir, "group_tags")


def _manifest_path() -> str:
    return os.path.join(_group_tags_dir(), "manifest.json")


def _search_index_path() -> str:
    return os.path.join(_group_tags_dir(), "search-index.pkl")


def _lazy_available() -> bool:
    return os.path.isfile(_manifest_path())


def _dictionary_yaml_paths(extension_dir: str) -> List[str]:
    paths: List[str] = []
    local_yaml_path = os.path.join(extension_dir, "group_tags", "default.yaml")
    if os.path.isfile(local_yaml_path):
        paths.append(local_yaml_path)

    group_dir = os.path.join(extension_dir, "group_tags")
    if os.path.isdir(group_dir):
        for name in sorted(os.listdir(group_dir)):
            if not name.endswith(".yaml") or name in ("default.yaml", "default.yaml.bak"):
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


def _cache_file_path() -> str:
    root = user_storage.user_root_dir()
    if root:
        return os.path.join(root, "tag-dictionary-cache.pkl")
    if _extension_dir:
        return os.path.join(_extension_dir, "data", "tag-dictionary-cache.pkl")
    return ""


def _section_cache_path(section_name: str) -> str:
    root = user_storage.user_root_dir()
    base = root or os.path.join(_extension_dir, "data")
    safe = _tag_dedupe_key(section_name).replace("/", "_") or "section"
    return os.path.join(base, "tag-section-cache", f"{safe}.pkl")


def _section_yaml_path(section_name: str) -> Optional[str]:
    meta = _manifest_sections.get(section_name)
    if not meta:
        return None
    rel = (meta.get("file") or "").strip()
    if not rel:
        return None
    return os.path.join(_group_tags_dir(), rel)


def _section_yaml_mtime(section_name: str) -> float:
    path = _section_yaml_path(section_name)
    if not path:
        return 0.0
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _reset_indexes() -> None:
    global _jp_map, _tag_by_name, _tags_by_path, _cached_paths, _cached_path_counts, _cached_path_entries
    _jp_map = {}
    _tag_by_name = {}
    _tags_by_path = {}
    _cached_paths = []
    _cached_path_counts = {}
    _cached_path_entries = []


def _append_to_indexes(items: List[Dict], start_idx: int) -> None:
    global _cached_path_entries

    seen_paths = {(p["section"], p["category"], p["group"]) for p in _cached_paths}

    for offset, item in enumerate(items):
        idx = start_idx + offset
        tag = (item.get("tag") or "").strip()
        jp = (item.get("jp") or "").strip()
        if tag:
            if tag not in _tag_by_name:
                _tag_by_name[tag] = item
            if jp and tag not in _jp_map:
                _jp_map[tag] = jp

        sec = item.get("section") or ""
        cat = item.get("category") or ""
        grp = item.get("group") or ""
        path_tuple = (sec, cat, grp)
        _tags_by_path.setdefault(path_tuple, []).append(idx)

        if path_tuple not in seen_paths:
            seen_paths.add(path_tuple)
            _cached_paths.append({"section": sec, "category": cat, "group": grp})


def _build_indexes(items: List[Dict]) -> None:
    _reset_indexes()
    if items:
        _append_to_indexes(items, 0)


def _load_manifest() -> None:
    global _manifest_sections, _manifest_sections_ordered, _cached_paths, _cached_path_counts, _cached_path_entries

    with open(_manifest_path(), encoding="utf-8") as f:
        manifest = json.load(f) or {}

    if manifest.get("version") != _MANIFEST_VERSION:
        raise ValueError("Unsupported manifest version")

    _manifest_sections = {}
    _manifest_sections_ordered = []
    for entry in manifest.get("sections") or []:
        name = (entry.get("name") or "").strip()
        if name:
            _manifest_sections[name] = entry
            _manifest_sections_ordered.append(entry)

    _cached_paths = list(manifest.get("paths") or [])
    _cached_path_counts = dict(manifest.get("pathCounts") or {})
    _cached_path_entries = list(manifest.get("pathEntries") or [])


def _load_search_index() -> None:
    global _search_index
    path = _search_index_path()
    if not os.path.isfile(path):
        _search_index = []
        return
    try:
        with open(path, "rb") as f:
            payload = pickle.load(f)
    except Exception:
        _search_index = []
        return
    if isinstance(payload, dict):
        _search_index = list(payload.get("rows") or [])
    elif isinstance(payload, list):
        _search_index = payload
    else:
        _search_index = []


def _try_load_section_cache(section_name: str) -> Optional[List[Dict]]:
    cache_path = _section_cache_path(section_name)
    if not cache_path or not os.path.isfile(cache_path):
        return None
    try:
        with open(cache_path, "rb") as f:
            payload = pickle.load(f)
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("version") != _SECTION_CACHE_VERSION:
        return None
    if payload.get("section") != section_name:
        return None
    if payload.get("yaml_mtime") != _section_yaml_mtime(section_name):
        return None
    if payload.get("preview_dir_mtime") != _preview_dir_mtime:
        return None
    items = payload.get("items")
    return list(items) if isinstance(items, list) else None


def _save_section_cache(section_name: str, items: List[Dict]) -> None:
    cache_path = _section_cache_path(section_name)
    if not cache_path:
        return
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    payload = {
        "version": _SECTION_CACHE_VERSION,
        "section": section_name,
        "yaml_mtime": _section_yaml_mtime(section_name),
        "preview_dir_mtime": _preview_dir_mtime,
        "items": items,
    }
    tmp = cache_path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, cache_path)
    except OSError:
        pass


def _merge_section_items(raw_items: List[Dict]) -> List[Dict]:
    kept: List[Dict] = []
    for item in raw_items:
        key = _tag_dedupe_key(item.get("tag") or "")
        if not key or key in _global_tag_keys:
            continue
        _global_tag_keys.add(key)
        kept.append(item)
    return kept


def _load_section_items(section_name: str) -> List[Dict]:
    cached = _try_load_section_cache(section_name)
    if cached is not None:
        return cached

    yaml_path = _section_yaml_path(section_name)
    if not yaml_path or not os.path.isfile(yaml_path):
        return []

    try:
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"[Prompt Composer] Failed to load section {section_name!r}: {e}")
        return []

    items = _parse_yaml_sections(data)
    _resolve_jp_labels(items)
    items = _dedupe_items(items)
    _save_section_cache(section_name, items)
    return items


def load_section(section_name: str) -> bool:
    """Load one section YAML into memory. Returns True when loaded or already present."""
    if not _loaded or not _lazy_mode:
        return False

    name = (section_name or "").strip()
    if not name or name not in _manifest_sections:
        return False
    if name in _loaded_sections:
        return True

    t0 = time.time()
    raw_items = _load_section_items(name)
    items = _merge_section_items(raw_items)
    if not items and raw_items:
        _loaded_sections.add(name)
        return True

    start_idx = len(_tags)
    _tags.extend(items)
    _append_to_indexes(items, start_idx)
    _loaded_sections.add(name)
    print(
        f"[Prompt Composer] Loaded section {name!r}: {len(items)} tags "
        f"({time.time() - t0:.1f}s, total loaded={len(_tags)})"
    )
    return True


def ensure_section_loaded(section_name: Optional[str]) -> None:
    if section_name:
        load_section(section_name)


def is_section_loaded(section_name: str) -> bool:
    return (section_name or "").strip() in _loaded_sections


def loaded_sections() -> List[str]:
    return sorted(_loaded_sections)


def lazy_mode() -> bool:
    return _lazy_mode


def _yaml_signature(yaml_paths: List[str]) -> List[Tuple[str, float]]:
    sig: List[Tuple[str, float]] = []
    for path in yaml_paths:
        try:
            sig.append((path, os.path.getmtime(path)))
        except OSError:
            sig.append((path, 0.0))
    return sig


def _try_load_legacy_cache(yaml_paths: List[str], preview_dir_mtime: float) -> Optional[Dict]:
    cache_path = _cache_file_path()
    if not cache_path or not os.path.isfile(cache_path):
        return None
    try:
        with open(cache_path, "rb") as f:
            payload = pickle.load(f)
    except Exception:
        return None
    if not isinstance(payload, dict) or payload.get("version") != _LEGACY_CACHE_VERSION:
        return None
    if payload.get("yaml_sig") != _yaml_signature(yaml_paths):
        return None
    if payload.get("preview_dir_mtime") != preview_dir_mtime:
        return None
    return payload


def _save_legacy_cache(yaml_paths: List[str], preview_dir_mtime: float) -> None:
    cache_path = _cache_file_path()
    if not cache_path:
        return
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    payload = {
        "version": _LEGACY_CACHE_VERSION,
        "yaml_sig": _yaml_signature(yaml_paths),
        "preview_dir_mtime": preview_dir_mtime,
        "tags": _tags,
        "paths": _cached_paths,
        "path_counts": _cached_path_counts,
        "path_entries": _cached_path_entries,
        "tags_by_path": _tags_by_path,
        "jp_map": _jp_map,
        "tag_by_name": _tag_by_name,
    }
    tmp = cache_path + ".tmp"
    try:
        with open(tmp, "wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        os.replace(tmp, cache_path)
    except OSError as e:
        print(f"[Prompt Composer] Could not write tag dictionary cache: {e}")


def _load_items_from_yaml(yaml_paths: List[str]) -> Tuple[List[Dict], List[str]]:
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
    return items, loaded_files


def _init_lazy() -> None:
    global _loaded, _lazy_mode, _tags, _loaded_sections, _global_tag_keys

    _lazy_mode = True
    _tags = []
    _loaded_sections = set()
    _global_tag_keys = set()
    _reset_indexes()
    _load_manifest()
    _load_search_index()
    _loaded = True

    total_tags = sum(int(v.get("tagCount") or 0) for v in _manifest_sections.values())
    print(
        f"[Prompt Composer] Tag dictionary ready (lazy): "
        f"{len(_manifest_sections)} sections, {len(_search_index)} indexed tags "
        f"(~{total_tags} total, section YAML on demand, previews deferred)"
    )


def _init_legacy(yaml_paths: List[str], preview_mtime: float) -> None:
    global _loaded, _lazy_mode, _tags

    _lazy_mode = False
    cached = _try_load_legacy_cache(yaml_paths, preview_mtime)
    if cached:
        _tags = cached.get("tags") or []
        globals()["_jp_map"] = cached.get("jp_map") or {}
        globals()["_tag_by_name"] = cached.get("tag_by_name") or {}
        globals()["_tags_by_path"] = cached.get("tags_by_path") or {}
        globals()["_cached_paths"] = cached.get("paths") or []
        globals()["_cached_path_counts"] = cached.get("path_counts") or {}
        globals()["_cached_path_entries"] = cached.get("path_entries") or []
        if not _cached_paths or not _tags_by_path:
            _build_indexes(_tags)
        _loaded = True
        print(
            f"[Prompt Composer] Loaded {len(_tags)} prompt dictionary tags from cache "
            f"(previews={len(_preview_by_tag)})"
        )
        return

    t0 = time.time()
    items, loaded_files = _load_items_from_yaml(yaml_paths)
    _resolve_jp_labels(items)
    before = len(items)
    items = _dedupe_items(items)
    removed = before - len(items)
    _tags = items
    _build_indexes(_tags)
    _loaded = True
    _save_legacy_cache(yaml_paths, preview_mtime)
    dup_note = f", deduped={removed}" if removed else ""
    print(
        f"[Prompt Composer] Loaded {len(_tags)} prompt dictionary tags "
        f"from {', '.join(loaded_files)} in {time.time() - t0:.1f}s "
        f"(previews={len(_preview_by_tag)}{dup_note}, cache written)"
    )


def init(extension_dir: str):
    """Prepare tag dictionary (manifest only in lazy mode)."""
    global _extension_dir, _previews_dir
    if _loaded:
        return

    _extension_dir = extension_dir
    _previews_dir = user_storage.tag_previews_dir(extension_dir)
    globals()["_previews_scanned"] = False
    globals()["_preview_scan_started"] = False
    preview_mtime = 0.0

    if _lazy_available():
        _init_lazy()
        return

    yaml_paths = _dictionary_yaml_paths(extension_dir)
    if not yaml_paths:
        print("[Prompt Composer] Tag dictionary YAML not found")
        globals()["_tags"] = []
        globals()["_loaded"] = True
        _build_indexes(_tags)
        return

    _ensure_previews_scanned()
    preview_mtime = _preview_dir_mtime
    _init_legacy(yaml_paths, preview_mtime)


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
        for variant in preview_filenames.preview_lookup_variants(kt):
            add_alias(variant, kt, path)
        first = kt.split(",", 1)[0].strip()
        for variant in preview_filenames.preview_lookup_variants(first):
            add_alias(variant, kt, path)
        for part in kt.split(","):
            part = part.strip()
            for variant in preview_filenames.preview_lookup_variants(part):
                add_alias(variant, kt, path)
            if part.startswith("(") and ":" in part:
                add_alias(part.split(":", 1)[0][1:].strip(), kt, path)

    _preview_alias_index = {alias: path for alias, (_known, path) in index.items()}


def _ensure_previews_scanned() -> None:
    """Build the preview filename index once (expensive; not run at startup)."""
    global _previews_scanned
    if _previews_scanned:
        return
    with _preview_scan_lock:
        if _previews_scanned:
            return
        _scan_previews(force=True)
        _previews_scanned = True


def _maybe_start_preview_scan_background() -> None:
    """Index tag-previews folder in a background thread after the dictionary is first used."""
    global _preview_scan_started
    if not _previews_dir or not os.path.isdir(_previews_dir):
        return
    with _preview_scan_lock:
        if _preview_scan_started or _previews_scanned:
            return
        _preview_scan_started = True

    def _run() -> None:
        try:
            _ensure_previews_scanned()
            print(f"[Prompt Composer] Tag preview index ready ({len(_preview_by_tag)} files)")
        except Exception as e:
            print(f"[Prompt Composer] Tag preview index failed: {e}")

    threading.Thread(target=_run, name="pc-tag-previews", daemon=True).start()


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

    if _previews_scanned:
        for variant in preview_filenames.preview_lookup_variants(tag):
            hit = _preview_by_tag.get(variant)
            if hit:
                return hit

    for variant in preview_filenames.preview_lookup_variants(tag):
        safe_base = preview_filenames.tag_to_preview_basename(variant)
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
    _ensure_previews_scanned()
    item = _tag_by_name.get((tag or "").strip())
    if item is None and _lazy_mode:
        for row in _search_index:
            if (row.get("tag") or "").strip() == (tag or "").strip():
                ensure_section_loaded(row.get("section") or "")
                item = _tag_by_name.get((tag or "").strip())
                break
    yaml_preview = (item or {}).get("preview") or ""
    return _resolve_preview_path(tag, yaml_preview)


def rescan_previews() -> int:
    global _previews_scanned, _preview_scan_started
    _scan_previews(force=True)
    _previews_scanned = True
    _preview_scan_started = True
    return len(_preview_by_tag)


def _public_item(item: Dict) -> Dict:
    out = dict(item)
    yaml_preview = (item.get("preview") or "").strip()
    tag = (item.get("tag") or "").strip()
    url = None
    if yaml_preview or _previews_scanned:
        url = preview_url_for_tag(tag, yaml_preview)
    elif tag:
        path = _resolve_preview_path(tag, yaml_preview, allow_related=False)
        if path:
            encoded_tag = urllib.parse.quote(tag, safe="")
            url = f"/prompt-composer/api/tags/preview?tag={encoded_tag}"
    out["previewUrl"] = url
    return out


def _item_from_index_row(row: Dict) -> Dict:
    return {
        "tag": row.get("tag") or "",
        "jp": row.get("jp") or "",
        "section": row.get("section") or "",
        "category": row.get("category") or "",
        "group": row.get("group") or "",
    }


def translate_exact(tag: str) -> str:
    if not _loaded:
        return ""
    t = (tag or "").strip()
    if not t:
        return ""
    jp = (_jp_map.get(t) or "").strip()
    if jp:
        return jp
    if _lazy_mode:
        for row in _search_index:
            if (row.get("tag") or "").strip() == t:
                return (row.get("jp") or "").strip()
    return ""


def _match_path_filters(
    section: Optional[str],
    category: Optional[str],
    group: Optional[str],
    item_section: str,
    item_category: str,
    item_group: str,
) -> bool:
    if section is not None and item_section != section:
        return False
    if category is not None and item_category != category:
        return False
    if group is not None and item_group != group:
        return False
    return True


def _collect_tags_for_path_filter(
    section: Optional[str],
    category: Optional[str],
    group: Optional[str],
) -> List[Dict]:
    """Return tags in manifest/YAML path order for the given filters."""
    pool: List[Dict] = []
    for path_dict in _cached_paths:
        sec = path_dict.get("section") or ""
        cat = path_dict.get("category") or ""
        grp = path_dict.get("group") or ""
        if not _match_path_filters(section, category, group, sec, cat, grp):
            continue
        path_tuple = (sec, cat, grp)
        for idx in _tags_by_path.get(path_tuple, []):
            pool.append(_tags[idx])
    return pool


def _search_tags_lazy(
    query: str,
    limit: int,
    offset: int,
    section: Optional[str],
    category: Optional[str],
    group: Optional[str],
) -> Dict:
    q = (query or "").strip().lower()
    has_path = any(v is not None for v in (section, category, group))

    if section is not None:
        ensure_section_loaded(section)

    if q:
        pool_rows: List[Dict] = []
        for row in _search_index:
            if not _match_path_filters(section, category, group, row.get("section") or "", row.get("category") or "", row.get("group") or ""):
                continue
            tag_l = (row.get("tag") or "").lower()
            jp_l = (row.get("jp") or "").lower()
            if q in tag_l or q in jp_l:
                pool_rows.append(row)

        total = len(pool_rows)
        page_rows = pool_rows[offset : offset + limit]
        sections_needed = sorted({(row.get("section") or "").strip() for row in page_rows if row.get("section")})
        for sec in sections_needed:
            load_section(sec)

        items: List[Dict] = []
        for row in page_rows:
            tag = (row.get("tag") or "").strip()
            item = _tag_by_name.get(tag) or _item_from_index_row(row)
            items.append(_public_item(item))
        return {
            "items": items,
            "total": total,
            "hasMore": offset + len(page_rows) < total,
            "offset": offset,
            "limit": limit,
        }

    if has_path:
        pool = _collect_tags_for_path_filter(section, category, group)
        total = len(pool)
        page = pool[offset : offset + limit]
        items = [_public_item(it) for it in page]
        return {
            "items": items,
            "total": total,
            "hasMore": offset + len(page) < total,
            "offset": offset,
            "limit": limit,
        }

    return {"items": [], "total": 0, "hasMore": False, "offset": offset, "limit": limit}


def search_tags(
    query: str = "",
    limit: int = 50,
    offset: int = 0,
    section: str | None = None,
    category: str | None = None,
    group: str | None = None,
) -> Dict:
    if not _loaded:
        return {"items": [], "total": 0, "hasMore": False, "offset": offset, "limit": limit}

    limit = max(1, min(int(limit or 50), 500))
    offset = max(0, int(offset or 0))

    _maybe_start_preview_scan_background()

    if _lazy_mode:
        return _search_tags_lazy(query, limit, offset, section, category, group)

    q = (query or "").strip().lower()
    has_path = any(v is not None for v in (section, category, group))

    def match_query(item: Dict) -> bool:
        if not q:
            return True
        return q in item["tag"].lower() or q in (item.get("jp") or "").lower()

    pool: List[Dict] = []
    if has_path and not q:
        pool = _collect_tags_for_path_filter(section, category, group)
    else:
        for item in _tags:
            if section is not None and item["section"] != section:
                continue
            if category is not None and item["category"] != category:
                continue
            if group is not None and item["group"] != group:
                continue
            if match_query(item):
                pool.append(item)

    total = len(pool)
    page = pool[offset : offset + limit]
    items = [_public_item(it) for it in page]
    return {
        "items": items,
        "total": total,
        "hasMore": offset + len(page) < total,
        "offset": offset,
        "limit": limit,
    }


def list_paths() -> List[Dict]:
    if not _loaded:
        return []
    return list(_cached_paths)


def list_sections() -> List[Dict]:
    """Manifest sections in file order (000, 001, …)."""
    if not _loaded:
        return []
    return list(_manifest_sections_ordered)


def path_tag_counts() -> Dict[str, int]:
    if not _loaded:
        return {}
    return dict(_cached_path_counts)


def path_count_entries() -> List[Dict]:
    if not _loaded:
        return []
    return list(_cached_path_entries)
