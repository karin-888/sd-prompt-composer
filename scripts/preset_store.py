""" -*- coding: UTF-8 -*-
Preset store for sd-prompt-composer (Preset Manager / presets.json only).

Per-column block saves live in block-saves.json via ips_collections_store — not here.
"""

import os
import json
import uuid
import time
from typing import Any, Dict, List, Optional

import user_storage

_presets_path = None


def storage_path():
    return _presets_path


def init(extension_dir):
    """Initialize with extension directory path."""
    global _presets_path
    _presets_path = user_storage.bootstrap_json(
        extension_dir, "presets.json", default_factory=dict
    )


def _preset_notes_dir() -> Optional[str]:
    if not _presets_path:
        return None
    return os.path.join(os.path.dirname(_presets_path), "preset-notes")


def _preset_markdown_path(preset_id: str) -> Optional[str]:
    notes_dir = _preset_notes_dir()
    if not notes_dir or not preset_id:
        return None
    return os.path.join(notes_dir, f"{preset_id}.md")


def _token_lines(tokens: Any) -> List[str]:
    lines: List[str] = []
    if not isinstance(tokens, list):
        return lines
    for tok in tokens:
        if not isinstance(tok, dict):
            continue
        text = str(tok.get("text") or tok.get("label") or "").strip()
        if not text:
            continue
        label = str(tok.get("label") or "").strip()
        if label and label != text:
            lines.append(f"- `{text}` — {label}")
        else:
            lines.append(f"- `{text}`")
    return lines


def build_preset_markdown(preset: Dict[str, Any], preset_id: str = "") -> str:
    """Build a human-readable Markdown document for a preset."""
    name = str(preset.get("name") or preset_id or "preset").strip()
    lines: List[str] = [f"# {name}", ""]
    if preset_id:
        lines.extend([f"- preset id: `{preset_id}`", ""])

    memo = str(preset.get("memo") or "").strip()
    if memo:
        lines.extend(["## キャラメモ", "", memo, ""])

    lines.extend(["## プロンプト構成", ""])
    blocks = preset.get("blocks") or []
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            label = str(block.get("label") or block.get("type") or "block").strip()
            token_lines = _token_lines(block.get("tokens"))
            if not token_lines:
                continue
            lines.append(f"### {label}")
            lines.extend(token_lines)
            lines.append("")

    neg_blocks = preset.get("negativeBlocks") or []
    if isinstance(neg_blocks, list):
        neg_lines: List[str] = []
        for block in neg_blocks:
            if not isinstance(block, dict):
                continue
            label = str(block.get("label") or block.get("type") or "negative").strip()
            token_lines = _token_lines(block.get("tokens"))
            if not token_lines:
                continue
            neg_lines.append(f"### {label}")
            neg_lines.extend(token_lines)
            neg_lines.append("")
        if neg_lines:
            lines.extend(["## Negative", ""])
            lines.extend(neg_lines)

    meta = [
        ("orderProfile", preset.get("orderProfile")),
        ("updatedAt", preset.get("updatedAt")),
        ("createdAt", preset.get("createdAt")),
    ]
    meta_lines = [f"- {key}: `{value}`" for key, value in meta if value]
    if meta_lines:
        lines.extend(["## メタ情報", ""])
        lines.extend(meta_lines)
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def _write_preset_markdown(preset_id: str, preset: Dict[str, Any]) -> None:
    path = _preset_markdown_path(preset_id)
    notes_dir = _preset_notes_dir()
    if not path or not notes_dir:
        return
    try:
        os.makedirs(notes_dir, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(build_preset_markdown(preset, preset_id))
    except OSError as e:
        print(f"[Prompt Composer] Error writing preset markdown: {e}")


def _delete_preset_markdown(preset_id: str) -> None:
    path = _preset_markdown_path(preset_id)
    if not path or not os.path.isfile(path):
        return
    try:
        os.remove(path)
    except OSError:
        pass


def preset_notes_dir() -> Optional[str]:
    return _preset_notes_dir()


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
        memo = str(preset.get("memo") or "").strip()
        result.append({
            "id": preset_id,
            "name": preset.get("name", ""),
            "orderProfile": preset.get("orderProfile", ""),
            "tags": preset.get("tags", []),
            "memo": memo,
            "memoFormat": preset.get("memoFormat", "markdown" if memo else ""),
            "hasMemo": bool(memo),
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
    
    memo = str(data.get("memo") or "").strip()
    preset = {
        "name": normalized_name,
        "blocks": data.get("blocks", []),
        "negativeBlocks": data.get("negativeBlocks", []),
        "orderProfile": data.get("orderProfile", "illustrious_standard"),
        "tags": data.get("tags", []),
        "memo": memo,
        "createdAt": created_at,
        "updatedAt": now,
    }
    if memo:
        preset["memoFormat"] = str(data.get("memoFormat") or "markdown").strip() or "markdown"
    
    presets[preset_id] = preset
    
    if _save_presets(presets):
        _write_preset_markdown(preset_id, preset)
        preset["id"] = preset_id
        return preset
    return None


def delete_preset(preset_id):
    """Delete a preset by ID. Returns True if deleted."""
    presets = _load_presets()
    if preset_id in presets:
        del presets[preset_id]
        if _save_presets(presets):
            _delete_preset_markdown(preset_id)
            return True
    return False
