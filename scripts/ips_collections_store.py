# -*- coding: UTF-8 -*-
"""User-defined IPS tag collections (save / edit / delete)."""

import os
import json
import uuid
import time
from typing import Any, Dict, List, Optional

import user_storage

_path: Optional[str] = None

BLOCK_TYPES = (
    "quality",
    "character",
    "subject",
    "appearance",
    "outfit",
    "expression",
    "composition",
    "background",
    "lighting",
    "style",
    "lora",
    "embedding",
    "negative",
)


def init(extension_dir: str) -> None:
    global _path
    _path = user_storage.bootstrap_json(
        extension_dir, "ips-collections.json", default_factory=dict
    )


def _load() -> Dict[str, Any]:
    if not _path or not os.path.isfile(_path):
        return {}
    try:
        with open(_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: Dict[str, Any]) -> bool:
    if not _path:
        return False
    try:
        os.makedirs(os.path.dirname(_path), exist_ok=True)
        with open(_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except OSError as e:
        print(f"[Prompt Composer] Error saving IPS collections: {e}")
        return False


def _normalize_name(name: str) -> str:
    return (name or "").strip()


def _opt_truthy(val: Any) -> bool:
    return val in (True, 1, "1", "true", "True")


def _normalize_tags(tags: Any) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not isinstance(tags, list):
        return out
    seen = set()
    allowed_src = frozenset({"lora", "embedding", "manual", "ips", "tagset", "asset"})
    for raw in tags:
        if not isinstance(raw, dict):
            continue
        label = str(raw.get("l") or raw.get("label") or "").strip()
        text = str(raw.get("t") or raw.get("tag") or raw.get("text") or "").strip()
        if not text:
            continue
        cat = str(raw.get("cat") or raw.get("category") or "").strip()
        src = str(raw.get("src") or raw.get("sourceType") or "").strip()
        key = (label, text, cat, src)
        if key in seen:
            continue
        seen.add(key)
        item: Dict[str, Any] = {"l": label or text, "t": text, "cat": cat}
        if src in allowed_src:
            item["src"] = src
        w = raw.get("w", raw.get("weight"))
        if w is not None and w != "":
            try:
                item["w"] = float(w)
            except (TypeError, ValueError):
                pass
        if _opt_truthy(raw.get("tw") or raw.get("isTrigger")):
            item["tw"] = 1
        if _opt_truthy(raw.get("hid") or raw.get("hidden")):
            item["hid"] = 1
        jp = str(raw.get("j") or raw.get("jp") or "").strip()
        if jp and jp not in (label, text):
            item["j"] = jp
        out.append(item)
    return out


def _normalize_block(block: str) -> str:
    b = (block or "character").strip()
    return b if b in BLOCK_TYPES else "character"


def list_collections(block: Optional[str] = None) -> List[Dict[str, Any]]:
    data = _load()
    result = []
    for cid, col in data.items():
        if block and _normalize_block(col.get("block", "character")) != _normalize_block(block):
            continue
        tags = col.get("tags") or []
        result.append(
            {
                "id": cid,
                "name": col.get("name", ""),
                "block": _normalize_block(col.get("block", "character")),
                "memo": col.get("memo", ""),
                "tagCount": len(tags),
                "createdAt": col.get("createdAt", ""),
                "updatedAt": col.get("updatedAt", ""),
            }
        )
    result.sort(key=lambda x: x.get("updatedAt", ""), reverse=True)
    return result


def get_collection(collection_id: str) -> Optional[Dict[str, Any]]:
    data = _load()
    col = data.get(collection_id)
    if not col:
        return None
    return {
        "id": collection_id,
        "name": col.get("name", ""),
        "block": _normalize_block(col.get("block", "character")),
        "memo": col.get("memo", ""),
        "tags": _normalize_tags(col.get("tags")),
        "createdAt": col.get("createdAt", ""),
        "updatedAt": col.get("updatedAt", ""),
    }


def save_collection(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name = _normalize_name(payload.get("name", ""))
    if not name:
        return None

    data = _load()
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    cid = payload.get("id")
    if not cid or cid not in data:
        cid = uuid.uuid4().hex[:12]
        created = now
    else:
        created = data[cid].get("createdAt", now)

    col = {
        "name": name,
        "block": _normalize_block(payload.get("block", "character")),
        "memo": str(payload.get("memo") or "").strip(),
        "tags": _normalize_tags(payload.get("tags")),
        "createdAt": created,
        "updatedAt": now,
    }
    data[cid] = col
    if not _save(data):
        return None
    out = dict(col)
    out["id"] = cid
    out["tagCount"] = len(col["tags"])
    return out


def delete_collection(collection_id: str) -> bool:
    data = _load()
    if collection_id not in data:
        return False
    del data[collection_id]
    return _save(data)
