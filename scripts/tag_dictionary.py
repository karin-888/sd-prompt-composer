""" -*- coding: UTF-8 -*-
Tag dictionary loader for Prompt Composer.

Reads tags from prompt-aio's YAML file and exposes a simple
in-memory search API for the FastAPI routes.
"""

import os
from typing import List, Dict

import yaml

_tags: List[Dict] = []
_loaded: bool = False
_jp_map: Dict[str, str] = {}


def init(extension_dir: str):
    """Load tag dictionary once at startup."""
    global _tags, _loaded, _jp_map
    if _loaded:
        return

    # Prefer local dictionary shipped with this extension:
    #   extensions/sd-prompt-composer/group_tags/default.yaml
    local_yaml_path = os.path.join(extension_dir, "group_tags", "default.yaml")

    # Backward-compatible fallback (when users still rely on prompt-aio enhanced):
    #   extensions/sd-webui-prompt-aio-enhanced/group_tags/default.yaml
    base_path = os.path.dirname(os.path.dirname(extension_dir))
    fallback_yaml_path = os.path.join(
        base_path, "extensions", "sd-webui-prompt-aio-enhanced", "group_tags", "default.yaml"
    )

    yaml_path = local_yaml_path if os.path.isfile(local_yaml_path) else fallback_yaml_path

    if not os.path.isfile(yaml_path):
        print(f"[Prompt Composer] Tag dictionary YAML not found: {yaml_path}")
        _tags = []
        _loaded = True
        return

    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"[Prompt Composer] Failed to load tag dictionary: {e}")
        _tags = []
        _loaded = True
        return

    items: List[Dict] = []

    # expected top-level: list of sections
    if not isinstance(data, list):
        data = []

    for section in data:
        section_name = section.get("name") or ""
        for cat in section.get("categories", []) or []:
            cat_name = cat.get("name") or ""
            for group in cat.get("groups", []) or []:
                group_name = group.get("name") or ""
                tags = group.get("tags", {}) or {}
                # tags is a mapping: {english_tag: japanese_desc}
                for key, jp in tags.items():
                    eng = str(key)
                    jp_text = str(jp) if jp is not None else ""
                    items.append(
                        {
                            "tag": eng,
                            "jp": jp_text,
                            "section": section_name,
                            "category": cat_name,
                            "group": group_name,
                        }
                    )

    _tags = items
    _jp_map = {}
    for it in _tags:
        tag = (it.get("tag") or "").strip()
        jp = (it.get("jp") or "").strip()
        if tag and jp and tag not in _jp_map:
            _jp_map[tag] = jp
    _loaded = True
    src = "local" if yaml_path == local_yaml_path else "prompt-aio"
    print(f"[Prompt Composer] Loaded {len(_tags)} prompt dictionary tags from default.yaml (source={src})")


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
            results.append(item)

    # If we filtered everything out with path, but no query, try again without path to provide something
    if not results and not q and not any([section, category, group]):
        return _tags[: max(1, min(limit, 200))]

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

