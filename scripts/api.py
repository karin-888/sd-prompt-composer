""" -*- coding: UTF-8 -*-
FastAPI routes for sd-prompt-composer.
Provides REST API endpoints for asset browsing, preset management,
and order profile retrieval.
"""

import os
import sys
import mimetypes
import json
import hashlib
import re
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

# Ensure our scripts directory is on sys.path when this file is imported directly
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

import asset_indexer
import preset_store
import order_profiles
import tag_dictionary
import user_data
import tag_suggest
import wildcards
import ips_data_loader
import ips_collections_store
import image_caption
from modules import shared, sd_hijack
import open_clip.tokenizer
import urllib.parse
import urllib.request
import urllib.error
import subprocess

# Machine-translation fallback cache (free + paid providers)
_tag_mt_cache: dict[str, str] = {}
_deepl_last_error: str = ""
_google_translate_last_error: str = ""
_argos_last_error: str = ""
_libre_last_error: str = ""


def _argos_translate_tag(mt_key: str, qtext: str) -> str:
    """Returns JP text via local Argos Translate if enabled; empty string on skip/failure."""
    global _argos_last_error
    _argos_last_error = ""
    enable = bool(getattr(shared.opts, "pc_argos_enable", False))
    if not enable:
        return ""
    txt = (qtext or "").replace("_", " ").strip()
    if not txt:
        return ""

    # Try Python package first (fast + local), then optional CLI fallback.
    try:
        import argostranslate.translate  # type: ignore

        langs = argostranslate.translate.get_installed_languages()
        from_lang = next((l for l in langs if getattr(l, "code", "") == "en"), None)
        to_lang = next((l for l in langs if getattr(l, "code", "") == "ja"), None)
        if from_lang and to_lang:
            tr = from_lang.get_translation(to_lang)
            jp = (tr.translate(txt) or "").strip()
            if jp:
                mk = (mt_key or "").strip()
                if mk:
                    _tag_mt_cache[mk] = jp
                return jp
        _argos_last_error = "Argos language package en->ja is not installed."
    except Exception as e:
        _argos_last_error = f"Python package error: {e}"

    try:
        # Optional CLI fallback: argos-translate --from-lang en --to-lang ja --text "..."
        out = subprocess.check_output(
            ["argos-translate", "--from-lang", "en", "--to-lang", "ja", "--text", txt],
            stderr=subprocess.STDOUT,
            timeout=8,
            text=True,
        )
        jp = (out or "").strip()
        if jp:
            mk = (mt_key or "").strip()
            if mk:
                _tag_mt_cache[mk] = jp
            return jp
        if not _argos_last_error:
            _argos_last_error = "Argos CLI returned empty translation."
    except Exception as e:
        if not _argos_last_error:
            _argos_last_error = f"CLI error: {e}"
    return ""


def _libre_translate_tag(mt_key: str, qtext: str) -> str:
    """Returns JP text via LibreTranslate API if enabled; empty string on skip/failure."""
    global _libre_last_error
    _libre_last_error = ""
    enable = bool(getattr(shared.opts, "pc_libre_enable", False))
    api_url = (getattr(shared.opts, "pc_libre_api_url", "") or "").strip()
    api_key = (getattr(shared.opts, "pc_libre_api_key", "") or "").strip()
    if not enable or not api_url:
        return ""
    txt = (qtext or "").replace("_", " ").strip()
    if not txt:
        return ""
    # Build candidate URLs: configured URL first, then common local fallbacks.
    candidates = []
    def _push_url(u: str):
        v = (u or "").strip()
        if v and v not in candidates:
            candidates.append(v)
    _push_url(api_url)
    # Helpful fallback when old config still points to :5000 but container is on :5001.
    if "127.0.0.1:5000/translate" in api_url or "localhost:5000/translate" in api_url:
        _push_url(api_url.replace(":5000/translate", ":5001/translate"))
    _push_url("http://127.0.0.1:5001/translate")
    _push_url("http://localhost:5001/translate")

    try:
        payload = {
            "q": txt,
            "source": "en",
            "target": "ja",
            "format": "text",
        }
        if api_key:
            payload["api_key"] = api_key
        body = json.dumps(payload).encode("utf-8")

        for url in candidates:
            raw = ""
            try:
                req = urllib.request.Request(
                    url,
                    data=body,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=8) as r:
                    raw = r.read().decode("utf-8", errors="replace")
            except urllib.error.HTTPError as e:
                err_body = ""
                try:
                    err_body = e.read().decode("utf-8", errors="replace")
                except Exception:
                    err_body = ""
                _libre_last_error = f"{url} -> HTTPError {getattr(e, 'code', '')}: {err_body[:300]}"
                # Try next candidate URL.
                continue
            except Exception as e:
                _libre_last_error = f"{url} -> Error: {e}"
                continue

            jp = ""
            try:
                data = json.loads(raw) if raw else {}
                jp = str(data.get("translatedText") or "").strip()
            except Exception:
                jp = ""

            if jp:
                mk = (mt_key or "").strip()
                if mk:
                    _tag_mt_cache[mk] = jp
                return jp

        if not _libre_last_error:
            _libre_last_error = "Empty translation (check LibreTranslate endpoint / rate-limit)."
    except Exception as e:
        _libre_last_error = f"Error: {e}"
    return ""


def _deepl_translate_tag(mt_key: str, qtext: str) -> str:
    """Returns JP text via DeepL if enabled; empty string on skip/failure."""
    global _deepl_last_error
    _deepl_last_error = ""
    enable = bool(getattr(shared.opts, "pc_deepl_enable", False))
    api_key = (getattr(shared.opts, "pc_deepl_api_key", "") or "").strip()
    api_url = (getattr(shared.opts, "pc_deepl_api_url", "") or "").strip()
    if not enable or not api_key or not api_url:
        return ""
    txt = (qtext or "").replace("_", " ").strip()
    if not txt:
        return ""
    try:
        payload = urllib.parse.urlencode(
            {
                "text": txt,
                "source_lang": "EN",
                "target_lang": "JA",
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            api_url,
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Authorization": f"DeepL-Auth-Key {api_key}",
            },
            method="POST",
        )
        raw = ""
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                raw = r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            _deepl_last_error = f"HTTPError {getattr(e, 'code', '')}: {body[:300]}"
            raw = body
        except Exception as e:
            _deepl_last_error = f"Error: {e}"
            raw = ""

        jp = ""
        try:
            data = json.loads(raw) if raw else {}
            tr = (data.get("translations") or [{}])[0]
            jp = str(tr.get("text") or "").strip()
        except Exception:
            jp = ""
        if jp:
            mk = (mt_key or "").strip()
            if mk:
                _tag_mt_cache[mk] = jp
        return jp or ""
    except Exception:
        return ""


def _google_translate_tag(mt_key: str, qtext: str) -> str:
    """
    Returns JP text via Google Cloud Translation API (v2 REST) if enabled.
    Users must enable the API for their GCP project and create an API key.
    """
    global _google_translate_last_error
    _google_translate_last_error = ""
    enable = bool(getattr(shared.opts, "pc_google_translate_enable", False))
    api_key = (getattr(shared.opts, "pc_google_translate_api_key", "") or "").strip()
    api_url_base = (
        getattr(shared.opts, "pc_google_translate_api_url", None)
        or "https://translation.googleapis.com/language/translate/v2"
    )
    if not isinstance(api_url_base, str):
        api_url_base = str(api_url_base)
    api_url_base = api_url_base.strip().rstrip("/")
    if not enable or not api_key:
        return ""
    txt = (qtext or "").replace("_", " ").strip()
    if not txt:
        return ""
    sep = "&" if "?" in api_url_base else "?"
    url = f"{api_url_base}{sep}key={urllib.parse.quote(api_key, safe='')}"
    payload_obj = {"q": [txt], "target": "ja", "format": "text"}
    try:
        body = json.dumps(payload_obj).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        raw = ""
        try:
            with urllib.request.urlopen(req, timeout=8) as r:
                raw = r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = ""
            _google_translate_last_error = f"HTTPError {getattr(e, 'code', '')}: {err_body[:300]}"
            raw = err_body
        except Exception as e:
            _google_translate_last_error = f"Error: {e}"
            raw = ""

        jp = ""
        try:
            data = json.loads(raw) if raw else {}
            translations = (((data.get("data") or {}).get("translations")) or []) if isinstance(data.get("data"), dict) else []
            if translations:
                jp = str((translations[0] or {}).get("translatedText") or "").strip()
        except Exception:
            jp = ""
        if jp:
            mk = (mt_key or "").strip()
            if mk:
                _tag_mt_cache[mk] = jp
        elif not _google_translate_last_error:
            _google_translate_last_error = "Empty translation (check API quota / billing / key)."
        return jp or ""
    except Exception as e:
        _google_translate_last_error = f"Error: {e}"
        return ""


_registered_fastapi_app_id: int | None = None


def register_api(app: FastAPI, extension_dir: str):
    """Register all API routes with the FastAPI app."""
    # Skip duplicate registration on the same FastAPI instance (app_started may run twice).
    # After Reload UI, Gradio creates a new app object — register routes again on that instance.
    global _registered_fastapi_app_id
    app_id = id(app)
    if _registered_fastapi_app_id == app_id:
        return
    _registered_fastapi_app_id = app_id

    @app.get("/prompt-composer/api/assets")
    async def api_get_assets(
        type: Optional[str] = None,
        subfolder: Optional[str] = None,
        search: Optional[str] = None,
        special: Optional[str] = None,
        limit: int = 200,
        offset: int = 0
    ):
        """Get asset list with optional filtering."""
        print(f"[Prompt Composer] API Request: type={type}, subfolder={subfolder}, search={search}, special={special}")
        if type == "checkpoint":
            assets = asset_indexer.list_checkpoints()
        else:
            assets = asset_indexer.scan_all_assets()
            if type:
                assets = [a for a in assets if a["type"] == type]
        
        # Specifically handle subfolder filter
        if subfolder is not None and subfolder != "(すべて)":
             # Match exactly, but normalize separators and ignore leading/trailing ones
             target_sf = subfolder.replace("\\", "/").strip("/")
             assets = [
                 a for a in assets 
                 if a.get("subfolder", "").replace("\\", "/").strip("/") == target_sf
             ]
        
        if search:
            search_lower = search.lower()
            assets = [
                a for a in assets
                if search_lower in a["name"].lower()
                or search_lower in a.get("displayName", "").lower()
                or any(search_lower in tw.lower() for tw in a.get("triggerWords", []))
            ]
            
        if special == "favorites":
            assets = [a for a in assets if user_data.is_favorite(a["id"])]
        elif special == "recent":
            assets = [a for a in assets if user_data.get_usage_count(a["id"]) > 0]
            # Sort by usage count descending
            assets.sort(key=lambda a: user_data.get_usage_count(a["id"]), reverse=True)
        
        total = len(assets)
        assets_page = assets[offset:offset + limit]
        
        # Strip file system paths from response for security
        safe_assets = []
        for a in assets_page:
            safe = {k: v for k, v in a.items() if k not in ("filePath",)}
            # Convert preview path to API URL
            if a.get("previewPath"):
                safe["previewUrl"] = f"/prompt-composer/api/assets/preview/{a['id']}"
            else:
                safe["previewUrl"] = None
            safe["isFavorite"] = user_data.is_favorite(a["id"])
            # Build direct Civitai page URL when possible
            civ_model_id = a.get("civitaiModelId")
            civ_ver_id = a.get("civitaiVersionId")
            if civ_ver_id and civ_model_id:
                safe["civitaiUrl"] = f"https://civitai.com/models/{civ_model_id}?modelVersionId={civ_ver_id}"
            elif civ_model_id:
                safe["civitaiUrl"] = f"https://civitai.com/models/{civ_model_id}"
            safe["usageCount"] = user_data.get_usage_count(a["id"])
            safe_assets.append(safe)
        
        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "assets": safe_assets
        }
    
    @app.get("/prompt-composer/api/assets/subfolders")
    async def api_get_subfolders(type: Optional[str] = None):
        """Get list of unique subfolders."""
        return {"subfolders": asset_indexer.get_subfolders(asset_type=type)}
    
    @app.get("/prompt-composer/api/assets/preview/{asset_id}")
    async def api_get_preview(asset_id: str):
        """Serve a preview image for an asset."""
        asset = asset_indexer.get_asset_by_id(asset_id)
        if not asset or not asset.get("previewPath"):
            return JSONResponse(
                status_code=404,
                content={"error": "Preview not found"}
            )
        
        preview_path = asset["previewPath"]
        if not os.path.isfile(preview_path):
            return JSONResponse(
                status_code=404,
                content={"error": "Preview file missing"}
            )
        
        # Determine MIME type
        mime_type, _ = mimetypes.guess_type(preview_path)
        if not mime_type:
            mime_type = "image/webp"
        
        return FileResponse(
            preview_path,
            media_type=mime_type,
            headers={"Cache-Control": "public, max-age=86400"}
        )
    
    @app.get("/prompt-composer/api/assets/rescan")
    async def api_rescan_assets():
        """Force rescan of asset directories."""
        asset_indexer.invalidate_cache()
        assets = asset_indexer.scan_all_assets(force=True)
        checkpoints = asset_indexer.list_checkpoints(force=True)
        return {
            "message": f"Rescan complete. Found {len(assets)} LoRA/Embedding assets and {len(checkpoints)} checkpoints."
        }

    @app.delete("/prompt-composer/api/assets/{asset_id}")
    async def api_delete_asset(asset_id: str):
        """
        Delete an asset file (LoRA/Embedding) from disk.
        This is irreversible and intended for manual cleanup of duplicated/bad files.
        """
        asset = asset_indexer.get_asset_by_id(asset_id)
        if not asset or not asset.get("filePath"):
            return JSONResponse(status_code=404, content={"error": "Asset not found"})

        if asset.get("type") == "checkpoint":
            return JSONResponse(status_code=403, content={"error": "Checkpoint files cannot be deleted from Prompt Composer"})

        file_path = asset.get("filePath")
        if not file_path:
            return JSONResponse(status_code=404, content={"error": "Asset filePath missing"})

        # Safety: only allow known model extensions.
        _, ext = os.path.splitext(file_path)
        ext = (ext or "").lower()
        if ext not in getattr(asset_indexer, "MODEL_EXTS", set()):
            return JSONResponse(status_code=403, content={"error": "Refusing to delete unsupported file type"})

        # Safety: ensure file lives under the configured LoRA/Embedding roots.
        try:
            folders = asset_indexer._get_model_folders()  # type: ignore[attr-defined]
            roots = [os.path.realpath(p) for p in (folders or {}).values() if p]
        except Exception:
            roots = []

        real_fp = os.path.realpath(file_path)
        if roots:
            allowed = any(
                real_fp == r or real_fp.startswith(r + os.sep)
                for r in roots
            )
            if not allowed:
                return JSONResponse(status_code=403, content={"error": "Refusing to delete outside allowed roots"})

        try:
            os.remove(file_path)
        except FileNotFoundError:
            # Already gone; treat as success.
            pass
        except OSError as e:
            return JSONResponse(status_code=500, content={"error": f"Failed to delete: {e}"})

        asset_indexer.invalidate_cache()
        return {"message": "Deleted"}
    
    # --- Preset endpoints ---
    
    @app.get("/prompt-composer/api/presets")
    async def api_list_presets():
        """List all presets (summary)."""
        presets = preset_store.list_presets()
        return {"presets": presets}
    
    @app.get("/prompt-composer/api/presets/{preset_id}")
    async def api_get_preset(preset_id: str):
        """Get a single preset with full data."""
        preset = preset_store.get_preset(preset_id)
        if not preset:
            return JSONResponse(
                status_code=404,
                content={"error": "Preset not found"}
            )
        return preset
    
    @app.post("/prompt-composer/api/presets")
    async def api_save_preset(data: dict):
        """Save or update a preset."""
        if not data.get("name"):
            return JSONResponse(
                status_code=400,
                content={"error": "Name is required"}
            )
        preset = preset_store.save_preset(data)
        if preset:
            return preset
        return JSONResponse(
            status_code=500,
            content={"error": "Failed to save preset"}
        )
    
    @app.delete("/prompt-composer/api/presets/{preset_id}")
    async def api_delete_preset(preset_id: str):
        """Delete a preset."""
        if preset_store.delete_preset(preset_id):
            return {"message": "Deleted"}
        return JSONResponse(
            status_code=404,
            content={"error": "Preset not found"}
        )
    
    # --- Favorites & Recently Used endpoints ---
    
    @app.get("/prompt-composer/api/favorites")
    async def api_get_favorites():
        """Get list of favorite asset IDs."""
        return {"favorites": user_data.get_favorites()}
    
    @app.post("/prompt-composer/api/favorites/{asset_id}")
    async def api_add_favorite(asset_id: str):
        """Add an asset to favorites."""
        user_data.add_favorite(asset_id)
        return {"message": "Added", "favorites": user_data.get_favorites()}
    
    @app.delete("/prompt-composer/api/favorites/{asset_id}")
    async def api_remove_favorite(asset_id: str):
        """Remove an asset from favorites."""
        user_data.remove_favorite(asset_id)
        return {"message": "Removed", "favorites": user_data.get_favorites()}
    
    @app.get("/prompt-composer/api/recently-used")
    async def api_get_recently_used():
        """Get recently used assets."""
        return {"recentlyUsed": user_data.get_recently_used()}
    
    @app.post("/prompt-composer/api/assets/{asset_id}/use")
    async def api_record_usage(asset_id: str):
        """Record that an asset was used."""
        user_data.record_usage(asset_id)
        return {"message": "Recorded"}
    
    # --- Order profile endpoints ---
    
    @app.get("/prompt-composer/api/order-profiles")
    async def api_get_order_profiles():
        """Get all order profiles."""
        profiles = order_profiles.get_profiles()
        return {"profiles": profiles}
    
    @app.get("/prompt-composer/api/order-profiles/{profile_id}")
    async def api_get_order_profile(profile_id: str):
        """Get a single order profile."""
        profile = order_profiles.get_profile(profile_id)
        if not profile:
            return JSONResponse(
                status_code=404,
                content={"error": "Profile not found"}
            )
        return profile

    @app.post("/prompt-composer/api/order-profiles")
    async def api_save_order_profile(data: dict):
        """Save (create/overwrite) a user order profile."""
        if not data.get("name"):
            return JSONResponse(status_code=400, content={"error": "Name is required"})
        if not isinstance(data.get("order"), list) or not data.get("order"):
            return JSONResponse(status_code=400, content={"error": "Order is required"})
        prof = order_profiles.save_profile(data)
        if prof:
            return prof
        return JSONResponse(status_code=500, content={"error": "Failed to save profile"})

    @app.delete("/prompt-composer/api/order-profiles/{profile_id}")
    async def api_delete_order_profile(profile_id: str):
        """Delete a user order profile."""
        if order_profiles.delete_profile(profile_id):
            return {"message": "Deleted"}
        return JSONResponse(status_code=404, content={"error": "Profile not found or cannot delete"})

    # --- Tag dictionary endpoints ---

    @app.get("/prompt-composer/api/tags")
    async def api_search_tags(
        q: Optional[str] = None,
        limit: int = 120,
        offset: int = 0,
        section: Optional[str] = None,
        category: Optional[str] = None,
        group: Optional[str] = None,
    ):
        """Search prompt tags from prompt-aio dictionary."""
        return tag_dictionary.search_tags(
            query=q or "",
            limit=limit,
            offset=offset,
            section=section,
            category=category,
            group=group,
        )

    @app.get("/prompt-composer/api/tags/preview")
    async def api_get_tag_preview(tag: str):
        """Serve a preview image for a dictionary tag."""
        tag = (tag or "").strip()
        if not tag:
            return JSONResponse(status_code=400, content={"error": "tag is required"})

        preview_path = tag_dictionary.get_preview_file(tag)
        if not preview_path or not os.path.isfile(preview_path):
            return JSONResponse(status_code=404, content={"error": "Preview not found"})

        mime_type, _ = mimetypes.guess_type(preview_path)
        if not mime_type:
            mime_type = "image/webp"

        return FileResponse(
            preview_path,
            media_type=mime_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.post("/prompt-composer/api/tags/previews/rescan")
    async def api_rescan_tag_previews():
        """Rescan tag-previews folder after adding new image files."""
        count = tag_dictionary.rescan_previews()
        return {"message": f"Rescan complete. Found {count} tag preview images."}

    @app.get("/prompt-composer/api/tag-paths")
    async def api_get_tag_paths():
        """Get list of available (section/category/group) paths."""
        paths = tag_dictionary.list_paths()
        return {
            "paths": paths,
            "counts": tag_dictionary.path_tag_counts(),
            "pathCounts": tag_dictionary.path_count_entries(),
            "sections": tag_dictionary.list_sections(),
            "lazy": tag_dictionary.lazy_mode(),
        }

    @app.post("/prompt-composer/api/tags/sections/load")
    async def api_load_tag_section(section: str = ""):
        """Load one tag-dictionary section YAML into memory."""
        name = (section or "").strip()
        if not name:
            return JSONResponse(status_code=400, content={"error": "section is required"})
        ok = tag_dictionary.load_section(name)
        if not ok:
            return JSONResponse(status_code=404, content={"error": f"section not found: {name}"})
        return {
            "ok": True,
            "section": name,
            "loaded": tag_dictionary.is_section_loaded(name),
            "loadedSections": tag_dictionary.loaded_sections(),
        }

    # --- txt2img Script list (mirror dropdown in Prompt Composer) ---

    @app.get("/prompt-composer/api/txt2img-scripts")
    async def api_txt2img_scripts():
        titles = ["None"]
        try:
            from modules import scripts as sd_scripts
            runner = sd_scripts.scripts_txt2img
            if not getattr(runner, "scripts", None):
                runner.initialize_scripts(False)
            selectable = sorted(
                getattr(runner, "selectable_scripts", []) or [],
                key=lambda script: script.sorting_priority,
            )
            for script in selectable:
                title = sd_scripts.wrap_call(
                    script.title, script.filename, "title", default=script.filename
                )
                titles.append(title or script.filename)
        except Exception:
            pass
        return {"scripts": titles}

    # --- IPS data (Infinite Prompt Studio dictionaries) ---

    @app.get("/prompt-composer/api/ips/status")
    async def api_ips_status():
        return ips_data_loader.get_status()

    @app.get("/prompt-composer/api/ips/modules")
    async def api_ips_modules():
        return {"modules": ips_data_loader.list_modules()}

    @app.get("/prompt-composer/api/ips/tags")
    async def api_ips_tags(
        module: str,
        q: Optional[str] = None,
        cat: Optional[str] = None,
        limit: int = 120,
    ):
        if not module:
            return JSONResponse(status_code=400, content={"error": "module is required"})
        items = ips_data_loader.search_module_tags(module, q=q or "", cat=cat, limit=limit)
        mod = next((m for m in ips_data_loader.list_modules() if m["id"] == module), None)
        return {
            "items": items,
            "module": module,
            "block": (mod or {}).get("block", "character"),
        }

    @app.get("/prompt-composer/api/ips/fashion/genres")
    async def api_ips_fashion_genres():
        return {"genres": ips_data_loader.list_fashion_genres()}

    @app.get("/prompt-composer/api/ips/fashion/presets")
    async def api_ips_fashion_presets(
        genre: str,
        q: Optional[str] = None,
        limit: int = 80,
    ):
        if not genre:
            return JSONResponse(status_code=400, content={"error": "genre is required"})
        return {
            "genre": genre,
            "items": ips_data_loader.list_fashion_presets(genre, q=q or "", limit=limit),
        }

    @app.get("/prompt-composer/api/ips/collections")
    async def api_ips_collections_list(block: Optional[str] = None):
        return {"collections": ips_collections_store.list_collections(block=block)}

    @app.get("/prompt-composer/api/ips/collections/{collection_id}")
    async def api_ips_collection_get(collection_id: str):
        col = ips_collections_store.get_collection(collection_id)
        if not col:
            return JSONResponse(status_code=404, content={"error": "Collection not found"})
        return col

    @app.post("/prompt-composer/api/ips/collections")
    async def api_ips_collection_save(data: dict):
        if not (data.get("name") or "").strip():
            return JSONResponse(status_code=400, content={"error": "Name is required"})
        col = ips_collections_store.save_collection(data)
        if col:
            return col
        return JSONResponse(status_code=500, content={"error": "Failed to save collection"})

    @app.delete("/prompt-composer/api/ips/collections/{collection_id}")
    async def api_ips_collection_delete(collection_id: str):
        if ips_collections_store.delete_collection(collection_id):
            return {"message": "Deleted"}
        return JSONResponse(status_code=404, content={"error": "Collection not found"})

    # --- Wildcards endpoints ---

    @app.get("/prompt-composer/api/wildcards")
    @app.get("/prompt-composer/api/wildcards")
    async def api_list_wildcards(force: bool = False, q: Optional[str] = None, limit: int = 5000):
        """
        List wildcard files for insertion. Returns tokens like '__folder/name__'.
        q filters by substring on path/token.
        """
        items = wildcards.list_wildcards(force=force, limit=0 if q and q.strip() else limit)
        sources = wildcards.list_sources()
        if q:
            qq = q.strip().lower()
            if qq:
                items = [
                    it for it in items
                    if qq in (it.get("path", "").lower() + " " + it.get("token", "").lower())
                ]
                if limit and len(items) > limit:
                    items = items[:limit]
        elif limit and len(items) > limit:
            items = items[:limit]
        return {"items": items, "sources": sources}

    # --- Tag autocomplete endpoints (Prompt Composer local) ---

    @app.get("/prompt-composer/api/tag-suggest")
    async def api_tag_suggest(q: Optional[str] = None, limit: int = 30):
        """
        Lightweight tag suggestion based on danbooru.csv from tagcomplete.
        Returns up to `limit` tags containing the query.
        """
        if not q:
            return {"items": []}
        try:
            suggestions = tag_suggest.suggest(q, limit=limit)
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
        return {"items": suggestions}

    @app.get("/prompt-composer/api/tag-translate")
    async def api_tag_translate(tag: str, debug: bool = False):
        """
        Translate an exact tag to JP (best-effort).
        Checks:
          1) tag_suggest CSV translations (tagcomplete/local)
          2) tag_dictionary YAML translations (group_tags/default.yaml)
          3) Free MT fallback: Argos(local) -> LibreTranslate
          4) Optional paid fallback: DeepL -> Google Cloud Translation API
        """
        t = (tag or "").strip()
        if not t:
            return {"tag": "", "jp": ""}

        def _normalize_for_lookup(raw: str) -> str:
            s = (raw or "").strip()
            if not s:
                return ""
            # (tag:1.2) / (tag:-1.0) -> tag
            m = re.match(r"^\((.+):(-?[0-9.]+)\)$", s)
            if m:
                s = (m.group(1) or "").strip()
            return s.strip()

        def _candidate_tags(raw: str):
            base = _normalize_for_lookup(raw)
            if not base:
                return []
            cands = []
            for cand in [base, base.lower(), base.replace(" ", "_"), base.replace("_", " ")]:
                c = (cand or "").strip()
                if c and c not in cands:
                    cands.append(c)
            return cands

        jp = ""
        lookup_tag = t
        for cand in _candidate_tags(t):
            lookup_tag = cand
            try:
                jp = (tag_suggest.translate_exact(cand) or "").strip()
            except Exception:
                jp = ""
            if jp:
                break
            try:
                jp = (tag_dictionary.translate_exact(cand) or "").strip()
            except Exception:
                jp = ""
            if jp:
                break

        # Machine translation fallbacks:
        # free providers first, then optional paid providers.
        if not jp:
            try:
                cands_mt = _candidate_tags(t)
                mt_key = (cands_mt[0] if cands_mt else _normalize_for_lookup(t) or "").strip()
                if mt_key:
                    cached = _tag_mt_cache.get(mt_key)
                    if cached:
                        jp = cached.strip()
                    else:
                        qtext = mt_key
                        jp = _argos_translate_tag(mt_key, qtext).strip()
                        if not jp:
                            jp = _libre_translate_tag(mt_key, qtext).strip()
                        if not jp:
                            jp = _deepl_translate_tag(mt_key, qtext).strip()
                        if not jp:
                            jp = _google_translate_tag(mt_key, qtext).strip()
            except Exception:
                jp = jp or ""
        if debug:
            deepl_enable = bool(getattr(shared.opts, "pc_deepl_enable", False))
            deepl_api_key = (getattr(shared.opts, "pc_deepl_api_key", "") or "").strip()
            deepl_api_url = (getattr(shared.opts, "pc_deepl_api_url", "") or "").strip()
            g_enable = bool(getattr(shared.opts, "pc_google_translate_enable", False))
            g_api_key = (getattr(shared.opts, "pc_google_translate_api_key", "") or "").strip()
            a_enable = bool(getattr(shared.opts, "pc_argos_enable", False))
            l_enable = bool(getattr(shared.opts, "pc_libre_enable", False))
            l_api_url = (getattr(shared.opts, "pc_libre_api_url", "") or "").strip()
            _c_mt = _candidate_tags(t)
            _mt_dbg_key = ((_c_mt[0] if _c_mt else _normalize_for_lookup(t)) or "").strip()
            return {
                "tag": t,
                "jp": jp,
                "deepl": {
                    "enable": deepl_enable,
                    "has_key": bool(deepl_api_key),
                    "api_url": deepl_api_url,
                    "cached": (_mt_dbg_key in _tag_mt_cache) if _mt_dbg_key else False,
                    "last_error": _deepl_last_error,
                },
                "google": {
                    "enable": g_enable,
                    "has_key": bool(g_api_key),
                    "cached": (_mt_dbg_key in _tag_mt_cache) if _mt_dbg_key else False,
                    "last_error": _google_translate_last_error,
                },
                "argos": {
                    "enable": a_enable,
                    "cached": (_mt_dbg_key in _tag_mt_cache) if _mt_dbg_key else False,
                    "last_error": _argos_last_error,
                },
                "libre": {
                    "enable": l_enable,
                    "api_url": l_api_url,
                    "cached": (_mt_dbg_key in _tag_mt_cache) if _mt_dbg_key else False,
                    "last_error": _libre_last_error,
                },
            }
        return {"tag": t, "jp": jp}

    # --- Tokenizer endpoints ---

    @app.get("/prompt-composer/api/token-count")
    async def api_token_count(text: str):
        """
        Return exact token count using WebUI's tokenizer rules.
        Returns token_count and max_length (target prompt token count).
        """
        if not text:
            return {"token_count": 0, "max_length": 0}

        # limit work to avoid heavy requests
        text = text[:2048]

        sd_model = getattr(shared, "sd_model", None)
        if sd_model is None:
            return JSONResponse(status_code=503, content={"error": "Model not loaded"})

        cond_stage_model = getattr(sd_model, "cond_stage_model", None)
        if cond_stage_model is None:
            return JSONResponse(status_code=503, content={"error": "cond_stage_model missing"})

        try:
            token_count, max_length = sd_hijack.model_hijack.get_prompt_lengths(text, cond_stage_model)
            return {"token_count": int(token_count), "max_length": int(max_length)}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

    @app.get("/prompt-composer/api/tokenize")
    async def api_tokenize(text: str):
        """
        Tokenize text using the same tokenizer used by WebUI (CLIP/OpenCLIP).
        Returns token_text list (no token_id) plus exact token_count/max_length.
        """
        if not text:
            return {"tokens": [], "token_count": 0, "max_length": 0}

        text = text[:2048]

        sd_model = getattr(shared, "sd_model", None)
        if sd_model is None:
            return JSONResponse(status_code=503, content={"error": "Model not loaded"})

        cond_stage_model = getattr(sd_model, "cond_stage_model", None)
        if cond_stage_model is None:
            return JSONResponse(status_code=503, content={"error": "cond_stage_model missing"})

        # exact counts
        token_count, max_length = sd_hijack.model_hijack.get_prompt_lengths(text, cond_stage_model)

        # tokenize to ids (best-effort across backends)
        ids = None
        try:
            if hasattr(cond_stage_model, "tokenize"):
                ids = cond_stage_model.tokenize([text])[0]
        except Exception:
            ids = None

        # OpenCLIP fallback (SDXL/Forge often uses this)
        if ids is None:
            try:
                ids = open_clip.tokenizer._tokenizer.encode(text)
            except Exception:
                ids = []

        # id -> token string using OpenCLIP decoder when available
        tokens = []
        dec = getattr(open_clip.tokenizer._tokenizer, "decoder", None)
        if isinstance(dec, dict):
            for tid in ids:
                t = dec.get(tid, str(tid))
                tokens.append(t)
        else:
            # last fallback: represent ids as strings
            tokens = [str(x) for x in ids]

        return {
            "tokens": tokens,
            "token_count": int(token_count),
            "max_length": int(max_length),
        }

    @app.get("/prompt-composer/api/vision-models")
    async def api_vision_models(provider: str = "openai"):
        """List vision-capable model IDs for a provider (openai, gemini, ollama)."""
        p = image_caption.normalize_provider(provider)
        models = image_caption.get_vision_models_for_provider(p)
        return {"provider": p, "models": models}

    @app.get("/prompt-composer/api/vision-split")
    async def api_vision_split(text: str = "", style: str = "detailed"):
        """Split vision caption into prompt phrases (comma-separated)."""
        style = image_caption.normalize_output_style(style)
        tags = image_caption.split_caption_to_tags(text, style)
        return {
            "tags": tags,
            "formatted": ", ".join(tags),
            "count": len(tags),
            "style": style,
        }
