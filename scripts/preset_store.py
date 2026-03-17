""" -*- coding: UTF-8 -*-
Preset store for sd-prompt-composer.
Handles CRUD operations for named prompt presets.
"""

import os
import json
import uuid
import time


_presets_path = None


def init(extension_dir):
    """Initialize with extension directory path."""
    global _presets_path
    _presets_path = os.path.join(extension_dir, "data", "presets.json")
    # Ensure file exists
    if not os.path.isfile(_presets_path):
        os.makedirs(os.path.dirname(_presets_path), exist_ok=True)
        with open(_presets_path, 'w', encoding='utf-8') as f:
            json.dump({}, f)


def _load_presets():
    """Load all presets from file."""
    if not _presets_path or not os.path.isfile(_presets_path):
        return {}
    try:
        with open(_presets_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_presets(presets):
    """Save all presets to file."""
    if not _presets_path:
        return False
    try:
        os.makedirs(os.path.dirname(_presets_path), exist_ok=True)
        with open(_presets_path, 'w', encoding='utf-8') as f:
            json.dump(presets, f, ensure_ascii=False, indent=2)
        return True
    except OSError as e:
        print(f"[Prompt Composer] Error saving presets: {e}")
        return False


def list_presets():
    """
    List all presets (summary only, without full block data).
    Returns list of {id, name, orderProfile, createdAt, updatedAt}
    """
    presets = _load_presets()
    result = []
    for preset_id, preset in presets.items():
        result.append({
            "id": preset_id,
            "name": preset.get("name", ""),
            "orderProfile": preset.get("orderProfile", ""),
            "tags": preset.get("tags", []),
            "memo": preset.get("memo", ""),
            "createdAt": preset.get("createdAt", ""),
            "updatedAt": preset.get("updatedAt", ""),
        })
    # Sort by updatedAt desc
    result.sort(key=lambda x: x.get("updatedAt", ""), reverse=True)
    return result


def _normalize_name(name: str) -> str:
    # allow "category/name" but normalize whitespace and slashes
    s = (name or "").strip()
    # collapse repeated slashes and trim
    while "//" in s:
        s = s.replace("//", "/")
    s = s.strip("/")
    return s


def find_preset_id_by_name(name: str):
    """Find a preset id by its name (exact match after normalization)."""
    presets = _load_presets()
    target = _normalize_name(name)
    if not target:
        return None
    for pid, p in presets.items():
        if _normalize_name(p.get("name", "")) == target:
            return pid
    return None


def get_preset(preset_id):
    """Get a single preset by ID. Returns full preset data or None."""
    presets = _load_presets()
    preset = presets.get(preset_id)
    if preset:
        preset["id"] = preset_id
    return preset


def save_preset(data):
    """
    Save a new preset or overwrite an existing one.
    
    data should contain:
        name (required), blocks, negativeBlocks, orderProfile,
        tags (optional), memo (optional), id (optional, for overwrite)
    
    Returns the saved preset with its ID.
    """
    presets = _load_presets()
    
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    
    # normalize & validate name
    normalized_name = _normalize_name(data.get("name", ""))
    if not normalized_name:
        return None

    preset_id = data.get("id")
    if not preset_id or preset_id not in presets:
        # If a preset with the same name exists, treat as overwrite
        existing_id = find_preset_id_by_name(normalized_name)
        if existing_id and existing_id in presets:
            preset_id = existing_id
            created_at = presets[preset_id].get("createdAt", now)
        else:
            preset_id = uuid.uuid4().hex[:12]
            created_at = now
    else:
        created_at = presets[preset_id].get("createdAt", now)
    
    preset = {
        "name": normalized_name,
        "blocks": data.get("blocks", []),
        "negativeBlocks": data.get("negativeBlocks", []),
        "orderProfile": data.get("orderProfile", "illustrious_standard"),
        "tags": data.get("tags", []),
        "memo": data.get("memo", ""),
        "createdAt": created_at,
        "updatedAt": now,
    }
    
    presets[preset_id] = preset
    
    if _save_presets(presets):
        preset["id"] = preset_id
        return preset
    return None


def delete_preset(preset_id):
    """Delete a preset by ID. Returns True if deleted."""
    presets = _load_presets()
    if preset_id in presets:
        del presets[preset_id]
        return _save_presets(presets)
    return False
