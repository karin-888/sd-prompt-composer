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
import user_storage

# Supported model file extensions
MODEL_EXTS = {".safetensors", ".ckpt", ".pt", ".bin"}
CHECKPOINT_EXTS = {".safetensors", ".ckpt"}
CHECKPOINT_EXT_BLACKLIST = (".vae.ckpt", ".vae.safetensors")

# Cache file path (set during init)
_cache_path = None
_assets_cache = None
_checkpoints_cache = None
_checkpoints_fingerprint = None
_extension_dir = None


def init(extension_dir):
    """Initialize with extension directory path."""
    global _cache_path, _extension_dir
    _extension_dir = extension_dir
    _cache_path = user_storage.bootstrap_json(extension_dir, "assets-cache.json")


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


def _get_checkpoint_folders():
    """Resolve checkpoint model roots (Stable-diffusion / --ckpt-dir)."""
    folders = []

    def _add(path):
        if not path:
            return
        try:
            real = os.path.realpath(path)
        except OSError:
            return
        if os.path.isdir(real) and real not in folders:
            folders.append(real)

    try:
        from modules import sd_models
        _add(sd_models.model_path)
    except Exception:
        pass

    root = paths_internal.data_path
    _add(os.path.join(root, "models", "Stable-diffusion"))
    _add(os.path.join(root, "models", "StableDiffusion"))

    try:
        ckpt_dir = getattr(shared.cmd_opts, "ckpt_dir", None)
        _add(ckpt_dir)
    except Exception:
        pass

    return folders


def _is_checkpoint_file(filename):
    low = filename.lower()
    if any(low.endswith(suffix) for suffix in CHECKPOINT_EXT_BLACKLIST):
        return False
    _, ext = os.path.splitext(filename)
    return ext.lower() in CHECKPOINT_EXTS


def _checkpoint_asset_from_file(file_path, folder_root, checkpoint_info=None):
    rel_path = os.path.relpath(file_path, folder_root).replace("\\", "/")
    subfolder = os.path.dirname(rel_path).replace("\\", "/") if os.path.dirname(rel_path) else ""
    preview_path = civitai_reader.find_preview_image(file_path)

    title = rel_path
    display = os.path.splitext(os.path.basename(file_path))[0]
    name_base = display
    shorthash = ""

    info = checkpoint_info
    if info is None:
        try:
            from modules import sd_models
            info = sd_models.CheckpointInfo(file_path)
        except Exception:
            info = None

    if info is not None:
        title = info.title or title
        display = info.short_title or info.title or display
        name_base = info.name_for_extra or name_base
        shorthash = getattr(info, "shorthash", None) or ""
        if not preview_path and getattr(info, "modelspec_thumbnail", None):
            thumb = info.modelspec_thumbnail
            if isinstance(thumb, str) and os.path.isfile(thumb):
                preview_path = thumb

    asset_id = hashlib.md5(f"checkpoint:{os.path.realpath(file_path)}".encode()).hexdigest()[:12]
    return {
        "id": asset_id,
        "type": "checkpoint",
        "fileName": os.path.basename(file_path),
        "filePath": file_path,
        "relativePath": rel_path,
        "subfolder": subfolder,
        "name": name_base,
        "displayName": display,
        "checkpointTitle": title,
        "previewPath": preview_path,
        "triggerWords": [],
        "defaultWeight": None,
        "baseModel": "",
        "tags": [],
        "description": "",
        "civitaiModelId": None,
        "insertTemplate": None,
        "preferredBlock": None,
        "shorthash": shorthash,
    }


def _compute_checkpoint_fingerprint(folders):
    fingerprint_parts = []
    for folder_path in folders:
        if not os.path.isdir(folder_path):
            continue
        file_count = 0
        newest_mtime = 0
        for root, dirs, files in os.walk(folder_path, followlinks=True):
            for f in files:
                if not _is_checkpoint_file(f):
                    continue
                file_count += 1
                try:
                    mtime = os.path.getmtime(os.path.join(root, f))
                    newest_mtime = max(newest_mtime, mtime)
                except OSError:
                    pass
        fingerprint_parts.append(f"{folder_path}:{file_count}:{newest_mtime:.0f}")
    return "|".join(fingerprint_parts)


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
    for asset in scan_all_assets():
        if asset["id"] == asset_id:
            return asset
    for asset in list_checkpoints():
        if asset["id"] == asset_id:
            return asset
    return None


def _assets_from_disk_cache():
    """Load cached asset list without scanning disks (for fast UI build / reload)."""
    global _assets_cache
    if _assets_cache is not None:
        return _assets_cache

    folders = _get_model_folders()
    if not folders or not _cache_path or not os.path.isfile(_cache_path):
        return None

    try:
        with open(_cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        if cache_data.get("fingerprint", "") != _compute_dir_fingerprint(folders):
            return None
        assets = cache_data.get("assets", [])
        if assets:
            _assets_cache = assets
        return assets or None
    except (json.JSONDecodeError, OSError):
        return None


def get_subfolders(asset_type=None, *, allow_full_scan=True):
    """Get list of unique subfolders for filtering, optionally by type."""
    if asset_type == "checkpoint":
        assets = list_checkpoints()
    else:
        assets = _assets_from_disk_cache()
        if assets is None and allow_full_scan:
            assets = scan_all_assets()
        elif assets is None:
            return []
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


def list_checkpoints(force=False):
    """
    List checkpoint models by scanning checkpoint folders on disk.
    Uses WebUI's CheckpointInfo / registry when available for stable titles.
    """
    global _checkpoints_cache, _checkpoints_fingerprint

    folders = _get_checkpoint_folders()
    if not folders:
        print("[Prompt Composer] No checkpoint folders found")
        return []

    fingerprint = _compute_checkpoint_fingerprint(folders)
    if not force and _checkpoints_cache is not None and fingerprint == _checkpoints_fingerprint:
        return _checkpoints_cache

    registry_by_path = {}
    try:
        from modules import sd_models
        if not sd_models.checkpoints_list:
            try:
                sd_models.list_models()
            except Exception as e:
                print(f"[Prompt Composer] Warning: sd_models.list_models(): {e}")
        for title, info in sd_models.checkpoints_list.items():
            try:
                registry_by_path[os.path.realpath(info.filename)] = info
            except OSError:
                continue
    except Exception as e:
        print(f"[Prompt Composer] Warning: checkpoint registry unavailable: {e}")

    assets = []
    seen_realpaths = set()

    for folder_path in folders:
        if not os.path.isdir(folder_path):
            continue
        for root, dirs, files in os.walk(folder_path, followlinks=True):
            for filename in files:
                if not _is_checkpoint_file(filename):
                    continue
                file_path = os.path.join(root, filename)
                try:
                    real_path = os.path.realpath(file_path)
                except OSError:
                    continue
                if real_path in seen_realpaths or not os.path.isfile(real_path):
                    continue
                seen_realpaths.add(real_path)
                info = registry_by_path.get(real_path)
                assets.append(_checkpoint_asset_from_file(file_path, folder_path, info))

    assets.sort(key=lambda a: (
        (a.get("subfolder") or "").lower(),
        (a.get("displayName") or a.get("name") or "").lower(),
    ))

    _checkpoints_cache = assets
    _checkpoints_fingerprint = fingerprint
    print(f"[Prompt Composer] Listed {len(assets)} checkpoints")
    return assets


def invalidate_cache():
    """Force cache invalidation."""
    global _assets_cache, _checkpoints_cache, _checkpoints_fingerprint
    _assets_cache = None
    _checkpoints_cache = None
    _checkpoints_fingerprint = None
    if _cache_path and os.path.isfile(_cache_path):
        try:
            os.remove(_cache_path)
        except OSError:
            pass
