""" -*- coding: UTF-8 -*-
Civitai Helper .civitai.info reader for sd-prompt-composer.
Reads model metadata from Civitai Helper sidecar files.
"""

import os
import json
from modules import shared


def read_civitai_info(info_path):
    """
    Read a .civitai.info JSON file and extract relevant fields.
    
    Returns dict with:
        model_name, model_type, trained_words, base_model,
        description, default_weight, images
    """
    try:
        with open(info_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None

    model_info = data.get("model", {})
    
    # Extract trigger/trained words
    trained_words = data.get("trainedWords", [])
    if trained_words and isinstance(trained_words, list):
        # Filter empty strings
        trained_words = [w.strip() for w in trained_words if w and w.strip()]
    else:
        trained_words = []

    # Extract preview image URLs from civitai
    images = []
    for img in data.get("images", []):
        url = img.get("url")
        nsfw_level = img.get("nsfwLevel", 1)
        if url and nsfw_level <= 4:  # Skip very NSFW images
            images.append({
                "url": url,
                "width": img.get("width"),
                "height": img.get("height"),
                "nsfwLevel": nsfw_level
            })

    # Extract prompt examples from image metadata
    example_prompts = []
    for img in data.get("images", []):
        meta = img.get("meta")
        if meta and isinstance(meta, dict):
            prompt = meta.get("prompt", "")
            neg = meta.get("negativePrompt", "")
            if prompt:
                example_prompts.append({
                    "prompt": prompt,
                    "negativePrompt": neg,
                    "sampler": meta.get("sampler", ""),
                    "steps": meta.get("steps"),
                    "cfgScale": meta.get("cfgScale"),
                    "seed": meta.get("seed")
                })

    result = {
        "model_name": model_info.get("name", ""),
        "model_type": model_info.get("type", "").lower(),  # "lora", "textualinversion"
        "trained_words": trained_words,
        "base_model": data.get("baseModel", ""),
        "description": data.get("description") or model_info.get("description", ""),
        "civitai_model_id": data.get("modelId"),
        "civitai_version_id": data.get("id"),
        "download_url": data.get("downloadUrl"),
        "images": images,
        "example_prompts": example_prompts,
        "download_count": data.get("stats", {}).get("downloadCount", 0),
        "thumbs_up": data.get("stats", {}).get("thumbsUpCount", 0),
    }

    return result


def find_civitai_info(model_path):
    """
    Given a model file path, find the corresponding .civitai.info file.
    Civitai Helper uses: basename.civitai.info
    e.g., MyLora.safetensors -> MyLora.civitai.info
    """
    base, _ = os.path.splitext(model_path)
    info_path = f"{base}.civitai.info"
    if os.path.isfile(info_path):
        return info_path
    return None


def find_preview_image(model_path):
    """
    Find the preview image for a model file.
    Checks: basename.preview.webp, .preview.png, .preview.jpg, .preview.jpeg
    Also checks: basename.png (some tools use direct name match)
    """
    base, _ = os.path.splitext(model_path)
    
    preview_exts = [
        ".preview.webp",
        ".preview.png", 
        ".preview.jpg",
        ".preview.jpeg",
        ".preview.gif",
    ]
    
    for ext in preview_exts:
        path = f"{base}{ext}"
        if os.path.isfile(path):
            return path

    # Fallback: direct name match (e.g., MyLora.png)
    for ext in [".png", ".jpg", ".jpeg", ".webp"]:
        path = f"{base}{ext}"
        if os.path.isfile(path):
            return path

    return None
