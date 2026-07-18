""" -*- coding: UTF-8 -*-
Wildcard helper for sd-prompt-composer.

Provides a lightweight list of wildcard .txt files available in common WebUI locations.
Primary source: extensions/sd-dynamic-prompts/wildcards
This is intended for UI insertion (e.g. __folder/name__) rather than expanding wildcards.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

_cache: Optional[List[Dict[str, str]]] = None
_last_sources: List[Dict[str, str]] = []

SD_DYNAMIC_PROMPTS_NAME = "sd-dynamic-prompts"


def _norm(p: str) -> str:
    return (p or "").replace("\\", "/").strip("/")


def _try_get_opt_path(attr: str) -> Optional[str]:
    try:
        from modules import shared  # type: ignore
        v = getattr(getattr(shared, "opts", None), attr, None)
        if not v:
            return None
        v = os.path.expanduser(str(v))
        if os.path.isdir(v):
            return v
        return None
    except Exception:
        return None


def _extensions_dir() -> Optional[str]:
    try:
        from modules.paths import extensions_dir  # type: ignore
        if extensions_dir and os.path.isdir(str(extensions_dir)):
            return str(extensions_dir)
    except Exception:
        pass
    # Fallback: this file lives in extensions/sd-prompt-composer/scripts/
    here = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.abspath(os.path.join(here, "..", ".."))
    if os.path.basename(cand) == "extensions" or os.path.isdir(
        os.path.join(cand, SD_DYNAMIC_PROMPTS_NAME)
    ):
        return cand
    return None


def _try_get_sd_dynamic_prompts_wildcards() -> Optional[str]:
    """Prefer sd-dynamic-prompts/wildcards (official get_wildcard_dir, then path resolve)."""
    try:
        from sd_dynamic_prompts.paths import get_wildcard_dir  # type: ignore
        p = get_wildcard_dir()
        if p is not None:
            ap = os.path.abspath(str(p))
            if os.path.isdir(ap):
                return ap
    except Exception:
        pass

    ext_dir = _extensions_dir()
    if ext_dir:
        cand = os.path.join(ext_dir, SD_DYNAMIC_PROMPTS_NAME, "wildcards")
        if os.path.isdir(cand):
            return os.path.abspath(cand)

    here = os.path.dirname(os.path.abspath(__file__))
    cand = os.path.abspath(os.path.join(here, "..", "..", SD_DYNAMIC_PROMPTS_NAME, "wildcards"))
    if os.path.isdir(cand):
        return cand
    return None


def _candidate_dirs() -> List[Tuple[str, str]]:
    """
    Returns list of (label, dir_path) candidates.
    Primary (and default) source: extensions/sd-dynamic-prompts/wildcards.
    Optional: Settings wildcards_dir / wildcard_dir when they point elsewhere.
    """
    out: List[Tuple[str, str]] = []

    sddp = _try_get_sd_dynamic_prompts_wildcards()
    if sddp:
        out.append(("sd-dynamic-prompts", sddp))

    for attr in ("wildcards_dir", "wildcard_dir"):
        p = _try_get_opt_path(attr)
        if p:
            out.append((attr, p))

    seen = set()
    deduped: List[Tuple[str, str]] = []
    for label, path in out:
        ap = os.path.abspath(path)
        if ap in seen:
            continue
        seen.add(ap)
        deduped.append((label, ap))
    return deduped


def list_sources() -> List[Dict[str, str]]:
    """Return last computed wildcard source directories."""
    global _last_sources
    if _last_sources:
        return _last_sources
    out: List[Dict[str, str]] = []
    for label, p in _candidate_dirs():
        out.append({"source": label, "dir": p})
    _last_sources = out
    return out


def _walk_txt_files(root: str) -> List[str]:
    files: List[str] = []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if not fn.lower().endswith(".txt"):
                continue
            files.append(os.path.join(dirpath, fn))
    return files


def _list_from_sd_dynamic_prompts() -> Optional[List[Dict[str, str]]]:
    """
    Use sd-dynamic-prompts' WildcardManager to list wildcards, including non-text sources
    (e.g. YAML collections). Returns None if the dependency isn't available.
    """
    try:
        from sd_dynamic_prompts.paths import get_wildcard_dir  # type: ignore
        from dynamicprompts.wildcards import WildcardManager  # type: ignore
    except Exception:
        return None

    try:
        wc_dir = get_wildcard_dir()
        manager = WildcardManager(wc_dir)
        root = manager.tree.root
    except Exception:
        return None

    out: List[Dict[str, str]] = []

    def walk(node) -> None:
        nonlocal out
        try:
            colls = sorted(list(getattr(node, "collections", [])))
        except Exception:
            colls = []
        for coll in colls:
            try:
                name = node.qualify_name(coll)
                token = manager.to_wildcard(name)
                out.append({"token": token, "path": name, "source": "sd-dynamic-prompts"})
            except Exception:
                continue

        try:
            child_nodes = getattr(node, "child_nodes", {}) or {}
            items = sorted(child_nodes.items(), key=lambda kv: kv[0])
        except Exception:
            items = []
        for _, child in items:
            walk(child)

    walk(root)
    out.sort(key=lambda x: x.get("path", ""))
    return out


def _to_wildcard_token(root: str, file_path: str) -> str:
    rel = os.path.relpath(file_path, root)
    rel = _norm(rel)
    if rel.lower().endswith(".txt"):
        rel = rel[:-4]
    return f"__{rel}__"


def _merge_items(base: List[Dict[str, str]], extra: List[Dict[str, str]]) -> List[Dict[str, str]]:
    merged: Dict[str, Dict[str, str]] = {}
    for it in (base or []) + (extra or []):
        token = (it.get("token") or "").strip()
        path = (it.get("path") or "").strip()
        if not token:
            continue
        key = token or path
        if key not in merged:
            merged[key] = {"token": token, "path": path, "source": it.get("source", "")}
        else:
            src = merged[key].get("source", "")
            add = it.get("source", "")
            if add and add not in src:
                merged[key]["source"] = (src + "," + add).strip(",")
    out = list(merged.values())
    out.sort(key=lambda x: x.get("path", "") or x.get("token", ""))
    return out


def _build_cache() -> List[Dict[str, str]]:
    """Scan all candidate dirs and return the full wildcard index."""
    scanned: List[Dict[str, str]] = []
    sources: List[Dict[str, str]] = []
    for source, root in _candidate_dirs():
        sources.append({"source": source, "dir": root})
        try:
            for fp in _walk_txt_files(root):
                token = _to_wildcard_token(root, fp)
                rel = _norm(os.path.relpath(fp, root))
                if rel.lower().endswith(".txt"):
                    rel = rel[:-4]
                scanned.append({"token": token, "path": rel, "source": source})
        except Exception:
            continue

    sddp_items = _list_from_sd_dynamic_prompts()
    if sddp_items is not None:
        # Keep filesystem scan as source of truth; merge manager extras (YAML etc.)
        out = _merge_items(scanned, sddp_items)
    else:
        out = _merge_items(scanned, [])

    global _last_sources
    _last_sources = sources
    return out


def list_wildcards(force: bool = False, limit: int = 5000) -> List[Dict[str, str]]:
    """
    List available wildcard files.
    Returns list of {token, path, source}.
      - token: '__folder/name__' form for insertion
      - path: relative path without extension (folder/name)
      - source: candidate label
    """
    global _cache
    if _cache is None or force:
        _cache = _build_cache()

    out = _cache
    if limit and len(out) > limit:
        out = out[:limit]
    return out


def get_wildcards_root() -> Optional[str]:
    """Absolute path to sd-dynamic-prompts/wildcards (create if missing)."""
    root = _try_get_sd_dynamic_prompts_wildcards()
    if root:
        return root
    ext_dir = _extensions_dir()
    if not ext_dir:
        return None
    cand = os.path.join(ext_dir, SD_DYNAMIC_PROMPTS_NAME, "wildcards")
    try:
        os.makedirs(cand, exist_ok=True)
        return os.path.abspath(cand)
    except Exception:
        return None


def _invalidate_cache() -> None:
    global _cache, _last_sources
    _cache = None
    _last_sources = []


def _safe_rel_path(rel_path: str) -> Optional[str]:
    """
    Normalize a relative wildcard path (no extension) and reject traversal.
    Returns normalized 'folder/name' or None if invalid.
    """
    raw = (rel_path or "").strip().replace("\\", "/")
    if not raw:
        return None
    if raw.lower().endswith(".txt"):
        raw = raw[:-4]
    raw = raw.strip("/")
    if not raw or ".." in raw.split("/") or raw.startswith("/"):
        return None
    # Disallow empty segments and control chars
    parts = [p.strip() for p in raw.split("/") if p.strip()]
    if not parts:
        return None
    for p in parts:
        if p in (".", "..") or "/" in p or "\\" in p:
            return None
        if any(ord(c) < 32 for c in p):
            return None
    return "/".join(parts)


def _abs_txt_path(rel_path: str) -> Optional[Tuple[str, str]]:
    """
    Resolve relative path to absolute .txt under wildcards root.
    Returns (root, abs_path) or None.
    """
    root = get_wildcards_root()
    if not root:
        return None
    safe = _safe_rel_path(rel_path)
    if not safe:
        return None
    abs_path = os.path.abspath(os.path.join(root, safe + ".txt"))
    root_abs = os.path.abspath(root)
    if abs_path != root_abs and not abs_path.startswith(root_abs + os.sep):
        return None
    return root_abs, abs_path


def read_wildcard(rel_path: str) -> Optional[Dict[str, str]]:
    """Read a wildcard .txt file. Returns {path, token, content, file}."""
    resolved = _abs_txt_path(rel_path)
    if not resolved:
        return None
    _root, abs_path = resolved
    if not os.path.isfile(abs_path):
        return None
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        return None
    safe = _safe_rel_path(rel_path)
    return {
        "path": safe or "",
        "token": f"__{safe}__",
        "content": content,
        "file": abs_path,
    }


def write_wildcard(rel_path: str, content: str, create: bool = False) -> Optional[Dict[str, str]]:
    """
    Write (overwrite or create) a wildcard .txt under sd-dynamic-prompts/wildcards.
    create=True allows creating a missing file; False requires existing file.
    """
    resolved = _abs_txt_path(rel_path)
    if not resolved:
        return None
    _root, abs_path = resolved
    exists = os.path.isfile(abs_path)
    if not exists and not create:
        return None
    try:
        parent = os.path.dirname(abs_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(abs_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(content if content is not None else "")
    except Exception:
        return None
    _invalidate_cache()
    safe = _safe_rel_path(rel_path)
    return {
        "path": safe or "",
        "token": f"__{safe}__",
        "content": content if content is not None else "",
        "file": abs_path,
        "created": not exists,
    }


def delete_wildcard(rel_path: str) -> bool:
    """Delete a wildcard .txt if it exists under the wildcards root."""
    resolved = _abs_txt_path(rel_path)
    if not resolved:
        return False
    _root, abs_path = resolved
    if not os.path.isfile(abs_path):
        return False
    try:
        os.remove(abs_path)
    except Exception:
        return False
    _invalidate_cache()
    return True


def rename_wildcard(old_rel: str, new_rel: str) -> Optional[Dict[str, str]]:
    """
    Rename/move a wildcard .txt within the wildcards root.
    Returns {path, token, content, file, from} or None on failure.

    On case-insensitive filesystems (typical macOS), a case-only rename is done
    via a temporary two-step rename so the directory listing casing updates.
    """
    old_safe = _safe_rel_path(old_rel)
    new_safe = _safe_rel_path(new_rel)
    if not old_safe or not new_safe:
        return None
    if old_safe == new_safe:
        data = read_wildcard(old_safe)
        if not data:
            return None
        data["from"] = old_safe
        return data

    old_resolved = _abs_txt_path(old_safe)
    new_resolved = _abs_txt_path(new_safe)
    if not old_resolved or not new_resolved:
        return None
    root_abs, old_abs = old_resolved
    _root2, new_abs = new_resolved
    if not os.path.isfile(old_abs):
        return None

    same_target = False
    try:
        if os.path.exists(new_abs):
            same_target = os.path.samefile(old_abs, new_abs)
            if not same_target:
                return None
    except OSError:
        if os.path.exists(new_abs):
            return None

    try:
        parent = os.path.dirname(new_abs)
        if parent:
            os.makedirs(parent, exist_ok=True)

        if same_target or old_safe.casefold() == new_safe.casefold():
            # Case-only (or same inode) rename needs an intermediate name.
            tmp_safe = f"{old_safe}.__pc_renaming__"
            tmp_resolved = _abs_txt_path(tmp_safe)
            if not tmp_resolved:
                return None
            _troot, tmp_abs = tmp_resolved
            if os.path.exists(tmp_abs) and not os.path.samefile(old_abs, tmp_abs):
                return None
            os.rename(old_abs, tmp_abs)
            try:
                os.rename(tmp_abs, new_abs)
            except Exception:
                # Best-effort rollback to the original path.
                try:
                    os.rename(tmp_abs, old_abs)
                except Exception:
                    pass
                return None
        else:
            os.rename(old_abs, new_abs)

        # Remove empty parent dirs left behind (best-effort, stay inside root)
        old_parent = os.path.dirname(old_abs)
        while old_parent and old_parent.startswith(root_abs + os.sep):
            try:
                os.rmdir(old_parent)
            except OSError:
                break
            old_parent = os.path.dirname(old_parent)
    except Exception:
        return None

    _invalidate_cache()
    # Prefer the actual directory-entry casing after rename.
    actual = _resolve_actual_rel_path(root_abs, new_safe) or new_safe
    try:
        with open(os.path.join(root_abs, actual + ".txt"), "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
    except Exception:
        content = ""
    return {
        "path": actual,
        "token": f"__{actual}__",
        "content": content,
        "file": os.path.abspath(os.path.join(root_abs, actual + ".txt")),
        "from": old_safe,
    }


def _resolve_actual_rel_path(root_abs: str, safe_rel: str) -> Optional[str]:
    """Return the on-disk relative path casing for safe_rel, if present."""
    parts = [p for p in (safe_rel or "").split("/") if p]
    if not parts:
        return None
    cur_dir = root_abs
    actual_parts: List[str] = []
    for i, part in enumerate(parts):
        is_last = i == len(parts) - 1
        try:
            entries = os.listdir(cur_dir)
        except OSError:
            return None
        if is_last:
            file_match = next(
                (
                    e
                    for e in entries
                    if e.lower().endswith(".txt") and e[:-4].casefold() == part.casefold()
                ),
                None,
            )
            if file_match:
                actual_parts.append(file_match[:-4])
                return "/".join(actual_parts)
            return None

        dir_match = next(
            (
                e
                for e in entries
                if e.casefold() == part.casefold() and os.path.isdir(os.path.join(cur_dir, e))
            ),
            None,
        )
        if not dir_match:
            return None
        actual_parts.append(dir_match)
        cur_dir = os.path.join(cur_dir, dir_match)
    return "/".join(actual_parts)
