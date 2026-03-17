""" -*- coding: UTF-8 -*-
Asset indexer for sd-prompt-composer.
Scans LoRA and Embedding directories, reads Civitai Helper info,
and builds a unified asset index with caching.
"""

import os
import sys
import json
import hashlib
import time
from pathlib import Path
import re

from modules import shared, paths_internal

# Ensure our own scripts directory is on sys.path when this file is imported
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import civitai_reader

# Supported model file extensions
MODEL_EXTS = {".safetensors", ".ckpt", ".pt", ".bin"}

# Cache file path (set during init)
_cache_path = None
_assets_cache = None
_extension_dir = None


def init(extension_dir):
    """Initialize with extension directory path."""
    global _cache_path, _extension_dir
    _extension_dir = extension_dir
    _cache_path = os.path.join(extension_dir, "data", "assets-cache.json")


def _get_model_folders():
    """
    Get LoRA and Embedding folder paths.
    Resolves symlinks and handles missing folders gracefully.
    """
    root = paths_internal.data_path
    
    folders = {
        "lora": os.path.join(root, "models", "Lora"),
        "embedding": os.path.join(root, "embeddings"),
    }
    
    # Override with command line options if set
    if hasattr(shared.cmd_opts, 'lora_dir') and shared.cmd_opts.lora_dir:
        if os.path.isdir(shared.cmd_opts.lora_dir):
            folders["lora"] = shared.cmd_opts.lora_dir
    
    if hasattr(shared.cmd_opts, 'embeddings_dir') and shared.cmd_opts.embeddings_dir:
        if os.path.isdir(shared.cmd_opts.embeddings_dir):
            folders["embedding"] = shared.cmd_opts.embeddings_dir

    # Resolve symlinks
    resolved = {}
    for key, path in folders.items():
        real_path = os.path.realpath(path)
        if os.path.isdir(real_path):
            resolved[key] = real_path
        elif os.path.isdir(path):
            resolved[key] = path
    
    return resolved


def _compute_dir_fingerprint(folders):
    """
    Compute a quick fingerprint of directories based on file count and newest mtime.
    Used to determine if cache is still valid.
    """
    fingerprint_parts = []
    
    for folder_type, folder_path in sorted(folders.items()):
        if not os.path.isdir(folder_path):
            continue
        
        file_count = 0
        newest_mtime = 0
        
        for root, dirs, files in os.walk(folder_path, followlinks=True):
            for f in files:
                _, ext = os.path.splitext(f)
                if ext.lower() in MODEL_EXTS:
                    file_count += 1
                    try:
                        mtime = os.path.getmtime(os.path.join(root, f))
                        newest_mtime = max(newest_mtime, mtime)
                    except OSError:
                        pass
        
        fingerprint_parts.append(f"{folder_type}:{file_count}:{newest_mtime:.0f}")
    
    return "|".join(fingerprint_parts)


def _scan_directory(folder_path, asset_type):
    """
    Scan a directory recursively for model files and build asset entries.
    
    asset_type: "lora" or "embedding"
    """
    assets = []
    
    if not os.path.isdir(folder_path):
        return assets
    
    for root, dirs, files in os.walk(folder_path, followlinks=True):
        for filename in files:
            _, ext = os.path.splitext(filename)
            if ext.lower() not in MODEL_EXTS:
                continue
            
            file_path = os.path.join(root, filename)
            rel_path = os.path.relpath(file_path, folder_path)
            
            # Determine subfolder (category)
            parts = Path(rel_path).parts
            subfolder = parts[0] if len(parts) > 1 else ""
            # Handle deeper nesting
            if len(parts) > 2:
                subfolder = os.path.join(*parts[:-1])
            
            # Generate stable ID from path
            asset_id = hashlib.md5(f"{asset_type}:{rel_path}".encode()).hexdigest()[:12]
            
            # Base name without extension
            name_base = os.path.splitext(filename)[0]
            
            # Read civitai info if available
            civitai_info = None
            info_path = civitai_reader.find_civitai_info(file_path)
            if info_path:
                civitai_info = civitai_reader.read_civitai_info(info_path)
            
            # Find preview image
            preview_path = civitai_reader.find_preview_image(file_path)
            
            # Build asset entry
            asset = {
                "id": asset_id,
                "type": asset_type,
                "fileName": filename,
                "filePath": file_path,
                "relativePath": rel_path,
                "subfolder": subfolder,
                "name": name_base,
                "displayName": name_base,
                "previewPath": preview_path,
                "triggerWords": [],
                "defaultWeight": 0.8 if asset_type == "lora" else None,
                "baseModel": "",
                "tags": [],
                "description": "",
                "civitaiModelId": None,
                "downloadCount": 0,
                "thumbsUp": 0,
            }
            
            # Enrich with civitai info
            if civitai_info:
                if civitai_info["model_name"]:
                    asset["displayName"] = civitai_info["model_name"]
                asset["triggerWords"] = civitai_info["trained_words"]
                asset["baseModel"] = civitai_info["base_model"]
                asset["description"] = civitai_info["description"] or ""
                asset["civitaiModelId"] = civitai_info["civitai_model_id"]
                asset["civitaiVersionId"] = civitai_info["civitai_version_id"]
                asset["civitaiDownloadUrl"] = civitai_info.get("download_url")
                asset["downloadCount"] = civitai_info["download_count"]
                asset["thumbsUp"] = civitai_info["thumbs_up"]
            
            # Build insert template
            if asset_type == "lora":
                weight = asset["defaultWeight"] or 0.8
                asset["insertTemplate"] = f"<lora:{name_base}:{weight}>"
            elif asset_type == "embedding":
                asset["insertTemplate"] = name_base
            
            # Determine preferred block
            asset["preferredBlock"] = _guess_preferred_block(
                asset_type, subfolder, name_base
            )
            
            assets.append(asset)
    
    return assets


def _guess_preferred_block(asset_type, subfolder, name):
    """
    Guess which Prompt Composer block this asset should be inserted into.
    Based on subfolder names and asset type.
    """
    if asset_type == "embedding":
        return "embedding"
    
    if asset_type == "lora":
        subfolder_lower = subfolder.lower()
        
        # Map Japanese subfolder names to block types
        folder_block_map = {
            "スタイル": "style",
            "style": "style",
            "背景": "background",
            "background": "background",
            "キャラクタ": "character",
            "キャラ": "character",
            "character": "character",
            "版権キャラ": "character",
            "衣装": "outfit",
            "outfit": "outfit",
            "ポーズ": "composition",
            "pose": "composition",
            "ディティール": "quality",
            "detail": "quality",
            "陰影": "lighting",
            "安定器": "quality",
            "スライダー": "quality",
            "slider": "quality",
            "flat": "style",
            "ドット絵": "style",
            "pixel": "style",
            "sd": "style",
            "chibi": "style",
            "ファンタジー": "style",
            "fantasy": "style",
            "身体": "appearance",
            "body": "appearance",
            "アイテ": "subject",
            "item": "subject",
        }
        
        for key, block in folder_block_map.items():
            if key in subfolder_lower:
                return block
        
        return "lora"
    
    return "lora"


def scan_all_assets(force=False):
    """
    Scan all LoRA and Embedding directories and build the asset index.
    Uses cache if available and still valid.
    
    Returns list of asset dicts.
    """
    global _assets_cache
    
    folders = _get_model_folders()
    
    if not folders:
        print("[Prompt Composer] No model folders found")
        return []
    
    # Check cache validity
    if not force and _assets_cache is not None:
        return _assets_cache
    
    if not force and _cache_path and os.path.isfile(_cache_path):
        try:
            with open(_cache_path, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
            
            cached_fingerprint = cache_data.get("fingerprint", "")
            current_fingerprint = _compute_dir_fingerprint(folders)
            
            if cached_fingerprint == current_fingerprint:
                _assets_cache = cache_data.get("assets", [])
                print(f"[Prompt Composer] Loaded {len(_assets_cache)} assets from cache")
                return _assets_cache
        except (json.JSONDecodeError, OSError):
            pass
    
    # Full scan
    print("[Prompt Composer] Scanning asset directories...")
    start_time = time.time()
    
    all_assets = []
    
    for asset_type, folder_path in folders.items():
        print(f"[Prompt Composer] Scanning {asset_type}: {folder_path}")
        assets = _scan_directory(folder_path, asset_type)
        all_assets.extend(assets)
        print(f"[Prompt Composer]   Found {len(assets)} {asset_type} assets")
    
    elapsed = time.time() - start_time
    print(f"[Prompt Composer] Scan complete: {len(all_assets)} total assets in {elapsed:.1f}s")
    
    # Save cache
    _save_cache(all_assets, folders)
    
    _assets_cache = all_assets
    return all_assets


def _save_cache(assets, folders):
    """Save asset index to cache file."""
    if not _cache_path:
        return
    
    fingerprint = _compute_dir_fingerprint(folders)
    
    cache_data = {
        "fingerprint": fingerprint,
        "scanned_at": time.time(),
        "assets": assets
    }
    
    try:
        os.makedirs(os.path.dirname(_cache_path), exist_ok=True)
        with open(_cache_path, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
        print(f"[Prompt Composer] Cache saved to {_cache_path}")
    except OSError as e:
        print(f"[Prompt Composer] Warning: Could not save cache: {e}")


def get_asset_by_id(asset_id):
    """Find an asset by its ID."""
    assets = scan_all_assets()
    for asset in assets:
        if asset["id"] == asset_id:
            return asset
    return None


def get_subfolders(asset_type=None):
    """Get list of unique subfolders for filtering, optionally by type."""
    assets = scan_all_assets()
    subfolders = set()
    for asset in assets:
        if asset_type and asset.get("type") != asset_type:
            continue
        sf = asset.get("subfolder", "")
        if sf:
            subfolders.add(sf)

    def _natural_key(s: str):
        # Split into digit / non-digit chunks so "10" > "2" numerically.
        parts = re.split(r"(\d+)", s)
        out = []
        for p in parts:
            if p.isdigit():
                try:
                    out.append(int(p))
                except ValueError:
                    out.append(p)
            else:
                out.append(p)
        return out

    return sorted(subfolders, key=_natural_key)


def invalidate_cache():
    """Force cache invalidation."""
    global _assets_cache
    _assets_cache = None
    if _cache_path and os.path.isfile(_cache_path):
        try:
            os.remove(_cache_path)
        except OSError:
            pass
