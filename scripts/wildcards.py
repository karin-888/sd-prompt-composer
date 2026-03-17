""" -*- coding: UTF-8 -*-
Wildcard helper for sd-prompt-composer.

Provides a lightweight list of wildcard .txt files available in common WebUI locations.
This is intended for UI insertion (e.g. __folder/name__) rather than expanding wildcards.
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Tuple

_cache: Optional[List[Dict[str, str]]] = None
_last_sources: List[Dict[str, str]] = []


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


def _try_get_webui_root_wildcards() -> Optional[str]:
    try:
        from modules import scripts  # type: ignore
        base = scripts.basedir()
        cand = os.path.join(base, "scripts", "wildcards")
        if os.path.isdir(cand):
            return cand
        return None
    except Exception:
        return None


def _try_get_extension_wildcard_dirs() -> List[str]:
    dirs: List[str] = []
    try:
        from modules.paths import extensions_dir  # type: ignore
        ext_dir = str(extensions_dir)
        if os.path.isdir(ext_dir):
            for name in os.listdir(ext_dir):
                cand = os.path.join(ext_dir, name, "wildcards")
                if os.path.isdir(cand):
                    dirs.append(cand)
    except Exception:
        pass
    return dirs


def _candidate_dirs() -> List[Tuple[str, str]]:
    """
    Returns list of (label, dir_path) candidates.
    """
    out: List[Tuple[str, str]] = []
    for attr in ("wildcards_dir", "wildcard_dir"):
        p = _try_get_opt_path(attr)
        if p:
            out.append((attr, p))
    p = _try_get_webui_root_wildcards()
    if p:
        out.append(("webui", p))
    for d in _try_get_extension_wildcard_dirs():
        out.append(("ext", d))
    # dedupe
    seen = set()
    deduped: List[Tuple[str, str]] = []
    for label, p in out:
        ap = os.path.abspath(p)
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


def _list_from_sd_dynamic_prompts(limit: int = 2000) -> Optional[List[Dict[str, str]]]:
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
        # collections/files
        try:
            colls = sorted(list(getattr(node, "collections", [])))
        except Exception:
            colls = []
        for coll in colls:
            try:
                name = node.qualify_name(coll)
                token = manager.to_wildcard(name)
                out.append({"token": token, "path": name, "source": "sd-dynamic-prompts"})
                if len(out) >= limit:
                    return
            except Exception:
                continue

        # child nodes (folders)
        try:
            child_nodes = getattr(node, "child_nodes", {}) or {}
            items = sorted(child_nodes.items(), key=lambda kv: kv[0])
        except Exception:
            items = []
        for _, child in items:
            if len(out) >= limit:
                return
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


def list_wildcards(force: bool = False, limit: int = 2000) -> List[Dict[str, str]]:
    """
    List available wildcard files.
    Returns list of {token, path, source}.
      - token: '__folder/name__' form for insertion
      - path: relative path without extension (folder/name)
      - source: candidate label
    """
    global _cache, _last_sources
    if _cache is not None and not force:
        return _cache

    def merge_items(base: List[Dict[str, str]], extra: List[Dict[str, str]]) -> List[Dict[str, str]]:
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
                # merge sources
                src = merged[key].get("source", "")
                add = it.get("source", "")
                if add and add not in src:
                    merged[key]["source"] = (src + "," + add).strip(",")
        out = list(merged.values())
        out.sort(key=lambda x: x.get("path", "") or x.get("token", ""))
        return out

    # 1) sd-dynamic-prompts (supports yaml collections etc.)
    sddp_items = _list_from_sd_dynamic_prompts(limit=limit)

    # 2) plain txt scanning in common dirs (and any other sources)
    scanned: List[Dict[str, str]] = []
    sources: List[Dict[str, str]] = [{"source": s, "dir": d} for s, d in _candidate_dirs()]
    for source, root in _candidate_dirs():
        try:
            for fp in _walk_txt_files(root):
                token = _to_wildcard_token(root, fp)
                rel = _norm(os.path.relpath(fp, root))
                if rel.lower().endswith(".txt"):
                    rel = rel[:-4]
                scanned.append({"token": token, "path": rel, "source": source})
                if len(scanned) >= limit:
                    break
        except Exception:
            continue
        if len(scanned) >= limit:
            break

    # 3) merge (allow txt + yaml mixed)
    if sddp_items is not None:
        sources = [{"source": "sd-dynamic-prompts", "dir": "sd_dynamic_prompts.get_wildcard_dir()"}] + sources
        out = merge_items(sddp_items, scanned)
    else:
        out = merge_items(scanned, [])

    _last_sources = sources

    # Respect limit after merge
    if len(out) > limit:
        out = out[:limit]

    # stable sort: path asc
    _cache = out
    return out

