""" -*- coding: UTF-8 -*-
Order profiles for sd-prompt-composer.
Manages prompt block ordering profiles for Illustrious and other models.
"""

import os
import json
import time
import re


_profiles_path = None
_profiles_cache = None


def init(extension_dir):
    """Initialize with extension directory path."""
    global _profiles_path, _profiles_cache
    _profiles_path = os.path.join(extension_dir, "data", "order-profiles.json")
    _profiles_cache = None


def _get_default_profile_ids():
    return set(_get_default_profiles().keys())


def _normalize_name(name: str) -> str:
    s = (name or "").strip()
    while "//" in s:
        s = s.replace("//", "/")
    s = s.strip("/")
    return s


def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^a-z0-9_\-]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "profile"


def _load_profiles_file():
    if not _profiles_path or not os.path.isfile(_profiles_path):
        return {}
    try:
        with open(_profiles_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return data
        return {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_profiles_file(profiles: dict) -> bool:
    if not _profiles_path:
        return False
    try:
        os.makedirs(os.path.dirname(_profiles_path), exist_ok=True)
        with open(_profiles_path, "w", encoding="utf-8") as f:
            json.dump(profiles, f, ensure_ascii=False, indent=2)
        return True
    except OSError as e:
        print(f"[Prompt Composer] Error saving order profiles: {e}")
        return False


def get_profiles():
    """Load and return all order profiles."""
    global _profiles_cache
    
    if _profiles_cache is not None:
        return _profiles_cache
    
    defaults = _get_default_profiles()
    user_profiles = _load_profiles_file()
    # merge, user profiles override only if ids don't collide with defaults
    merged = dict(defaults)
    for pid, prof in user_profiles.items():
        if pid in defaults:
            # never allow overwriting built-ins from disk
            continue
        if isinstance(prof, dict):
            merged[pid] = prof
    _profiles_cache = merged
    
    return _profiles_cache


def get_profile(profile_id):
    """Get a single profile by ID."""
    profiles = get_profiles()
    return profiles.get(profile_id)


def get_block_order(profile_id):
    """Get the block order list for a profile."""
    profile = get_profile(profile_id)
    if profile:
        return profile.get("order", [])
    return _get_default_profiles()["illustrious_standard"]["order"]


def find_profile_id_by_name(name: str):
    target = _normalize_name(name)
    if not target:
        return None
    profiles = get_profiles()
    for pid, prof in profiles.items():
        if _normalize_name(prof.get("name", "")) == target:
            return pid
    return None


def save_profile(data: dict):
    """
    Save a user order profile (display order only).
    data: {id?: str, name: str, order: list[str]}
    """
    global _profiles_cache
    name = _normalize_name(data.get("name", ""))
    order = data.get("order") or []
    if not name or not isinstance(order, list) or not order:
        return None

    defaults = _get_default_profiles()
    user_profiles = _load_profiles_file()
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    pid = data.get("id")
    if pid and pid in defaults:
        # don't overwrite built-ins
        pid = None

    if not pid:
        existing = find_profile_id_by_name(name)
        if existing and existing not in defaults:
            pid = existing
        else:
            pid = f"user_{_slugify(name)}"
            # ensure uniqueness
            if pid in defaults or pid in user_profiles:
                pid = f"{pid}_{int(time.time())}"

    user_profiles[pid] = {
        "name": name,
        "description": data.get("description", "ユーザー保存プロファイル"),
        "order": order,
        "updatedAt": now,
    }
    if _save_profiles_file(user_profiles):
        _profiles_cache = None
        p = dict(user_profiles[pid])
        p["id"] = pid
        return p
    return None


def delete_profile(profile_id: str) -> bool:
    global _profiles_cache
    if not profile_id:
        return False
    if profile_id in _get_default_profile_ids():
        return False
    user_profiles = _load_profiles_file()
    if profile_id in user_profiles:
        del user_profiles[profile_id]
        ok = _save_profiles_file(user_profiles)
        if ok:
            _profiles_cache = None
        return ok
    return False


def _get_default_profiles():
    """Return built-in default profiles."""
    return {
        "illustrious_standard": {
            "name": "Illustrious標準",
            "description": "Illustrious系モデルの標準的なプロンプト順序",
            "order": [
                "quality", "subject", "character", "appearance",
                "outfit", "expression", "composition", "background",
                "lighting", "style", "lora", "embedding"
            ]
        },
        "character_focus": {
            "name": "キャラ重視",
            "description": "キャラクター描写を優先する構成",
            "order": [
                "character", "appearance", "outfit", "expression",
                "quality", "subject", "composition", "background",
                "lighting", "style", "lora", "embedding"
            ]
        },
        "background_focus": {
            "name": "背景重視",
            "description": "背景・風景描写を優先する構成",
            "order": [
                "quality", "background", "lighting", "composition",
                "style", "subject", "character", "appearance",
                "outfit", "expression", "lora", "embedding"
            ]
        }
    }
