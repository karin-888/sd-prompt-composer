""" -*- coding: UTF-8 -*-
User data manager for sd-prompt-composer.
Handles favorites, usage history, and per-user asset preferences.
"""

import os
import json
import time


_data_path = None
_data_cache = None


def init(extension_dir):
    """Initialize with extension directory path."""
    global _data_path
    _data_path = os.path.join(extension_dir, "data", "user-data.json")
    if not os.path.isfile(_data_path):
        os.makedirs(os.path.dirname(_data_path), exist_ok=True)
        _save_data(_get_default_data())


def _get_default_data():
    return {
        "favorites": [],
        "recentlyUsed": [],
        "usageCounts": {}
    }


def _load_data():
    global _data_cache
    if _data_cache is not None:
        return _data_cache
    if not _data_path or not os.path.isfile(_data_path):
        _data_cache = _get_default_data()
        return _data_cache
    try:
        with open(_data_path, 'r', encoding='utf-8') as f:
            _data_cache = json.load(f)
    except (json.JSONDecodeError, OSError):
        _data_cache = _get_default_data()
    return _data_cache


def _save_data(data):
    global _data_cache
    _data_cache = data
    if not _data_path:
        return False
    try:
        os.makedirs(os.path.dirname(_data_path), exist_ok=True)
        with open(_data_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError as e:
        print(f"[Prompt Composer] Error saving user data: {e}")
        return False


# ===== Favorites =====

def get_favorites():
    """Get list of favorite asset IDs."""
    data = _load_data()
    return data.get("favorites", [])


def add_favorite(asset_id):
    """Add an asset to favorites."""
    data = _load_data()
    favs = data.get("favorites", [])
    if asset_id not in favs:
        favs.insert(0, asset_id)
        data["favorites"] = favs
        _save_data(data)
    return True


def remove_favorite(asset_id):
    """Remove an asset from favorites."""
    data = _load_data()
    favs = data.get("favorites", [])
    if asset_id in favs:
        favs.remove(asset_id)
        data["favorites"] = favs
        _save_data(data)
        return True
    return False


def is_favorite(asset_id):
    """Check if an asset is a favorite."""
    return asset_id in get_favorites()


# ===== Recently Used =====

MAX_RECENT = 30

def get_recently_used():
    """Get list of recently used asset entries: [{id, timestamp}, ...]"""
    data = _load_data()
    return data.get("recentlyUsed", [])


def record_usage(asset_id):
    """Record that an asset was used. Updates recency and count."""
    data = _load_data()
    
    # Update recently used list
    recent = data.get("recentlyUsed", [])
    # Remove existing entry for this asset
    recent = [r for r in recent if r.get("id") != asset_id]
    # Add to front
    recent.insert(0, {"id": asset_id, "timestamp": time.time()})
    # Trim to max
    data["recentlyUsed"] = recent[:MAX_RECENT]
    
    # Update usage count
    counts = data.get("usageCounts", {})
    counts[asset_id] = counts.get(asset_id, 0) + 1
    data["usageCounts"] = counts
    
    _save_data(data)


def get_usage_count(asset_id):
    """Get usage count for an asset."""
    data = _load_data()
    return data.get("usageCounts", {}).get(asset_id, 0)


def invalidate_cache():
    """Force reload from disk."""
    global _data_cache
    _data_cache = None
