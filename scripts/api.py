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
from modules import shared, sd_hijack
import open_clip.tokenizer


def register_api(app: FastAPI, extension_dir: str):
    """Register all API routes with the FastAPI app."""
    
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
        return {"message": f"Rescan complete. Found {len(assets)} assets."}
    
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
        limit: int = 50,
        section: Optional[str] = None,
        category: Optional[str] = None,
        group: Optional[str] = None,
    ):
        """Search prompt tags from prompt-aio dictionary."""
        items = tag_dictionary.search_tags(
            query=q or "",
            limit=limit,
            section=section,
            category=category,
            group=group,
        )
        return {"items": items}

    @app.get("/prompt-composer/api/tag-paths")
    async def api_get_tag_paths():
        """Get list of available (section/category/group) paths."""
        paths = tag_dictionary.list_paths()
        return {"paths": paths}

    # --- Wildcards endpoints ---

    @app.get("/prompt-composer/api/wildcards")
    async def api_list_wildcards(force: bool = False, q: Optional[str] = None, limit: int = 2000):
        """
        List wildcard files for insertion. Returns tokens like '__folder/name__'.
        q filters by substring on path/token.
        """
        items = wildcards.list_wildcards(force=force, limit=limit)
        sources = wildcards.list_sources()
        if q:
            qq = q.strip().lower()
            if qq:
                items = [
                    it for it in items
                    if qq in (it.get("path", "").lower() + " " + it.get("token", "").lower())
                ]
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
