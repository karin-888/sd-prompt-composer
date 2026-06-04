# -*- coding: UTF-8 -*-
"""Reference image → natural-language / tag-style prompts for Prompt Composer."""

from __future__ import annotations

import base64
import io
import json
import re
import urllib.error
import urllib.request
from typing import List, Optional, Tuple

from PIL import Image

from modules import shared

FOCUS_CHOICES = ["clothing", "character", "scene", "all"]
PROVIDER_CHOICES = ["blip", "ollama", "gemini", "openai"]

# Gradio 3.x does not support (label, value) tuples in Dropdown; map display labels here.
_FOCUS_FROM_LABEL = {
    "👗 衣装・小物のみ": "clothing",
    "👤 キャラ（服含む）": "character",
    "🌄 背景・構図": "scene",
    "🖼️ 画像全体": "all",
}
_PROVIDER_FROM_LABEL = {
    "BLIP（ローカル・無料）": "blip",
    "Ollama（ローカルLLM）": "ollama",
    "Gemini（API）": "gemini",
    "ChatGPT（OpenAI API）": "openai",
}
_LANGUAGE_FROM_LABEL = {
    "English（推奨）": "en",
    "日本語": "ja",
}
STYLE_CHOICES = ["detailed", "simple"]
_STYLE_FROM_LABEL = {
    "📝 詳細プロンプト（推奨）": "detailed",
    "🏷️ シンプル単語": "simple",
}

_DETAILED_FORMAT_RULES = (
    "Output format (strict):\n"
    "- ONE single line only.\n"
    "- Comma-separated prompt fragments for Stable Diffusion / Illustrious.\n"
    "- Use underscores instead of spaces in each fragment (danbooru style), e.g. white_bishop_sleeves.\n"
    "- For key garment elements use emphasis syntax (fragment:1.1) to (fragment:1.3).\n"
    "- Write 12-28 fragments: garment type, silhouette, length, collar, bodice, panels, bows, "
    "ornaments, belt, sleeves, cuffs, skirt layers, colors, materials (satin, lace, leather), "
    "trims, footwear, socks, bags, overall style adjectives.\n"
    "- No full sentences. No line breaks. No numbering.\n"
    "- Example style (structure only, describe the actual image): "
    "(a_white_and_black_gothic_lolita_nun-inspired_dress:1.2), short_knee-length_flared_dress, "
    "oversized_white_sailor_collar, black_waist_belt_with_silver_buckle, voluminous_white_bishop_sleeves, "
    "black_lace-up_ankle_boots, elegant_sacred_gothic_fashion"
)

# Vision-capable models (settings dropdown defaults)
OPENAI_VISION_MODELS_DEFAULT: List[str] = [
    "gpt-5.4",
    "gpt-5.5",
    "gpt-5",
    "gpt-5-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.5",
    "o4-mini",
    "o3",
    "o1",
]

GEMINI_VISION_MODELS_DEFAULT: List[str] = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash",
    "gemini-1.5-pro",
]

OLLAMA_VISION_MODELS_DEFAULT: List[str] = [
    "llava",
    "llava:13b",
    "moondream",
    "llama3.2-vision",
    "bakllava",
    "llava-llama3",
    "minicpm-v",
]


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        v = (item or "").strip()
        if not v or v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def _ensure_current_in_choices(choices: List[str], current: Optional[str]) -> List[str]:
    cur = (current or "").strip()
    merged = list(choices)
    if cur and cur not in merged:
        merged.insert(0, cur)
    return merged


def _openai_model_likely_vision(model_id: str) -> bool:
    m = (model_id or "").lower()
    if not m:
        return False
    blocked = (
        "embedding",
        "tts",
        "whisper",
        "dall-e",
        "davinci",
        "babbage",
        "moderation",
        "transcribe",
        "realtime",
        "audio",
        "image-generation",
    )
    if any(b in m for b in blocked):
        return False
    patterns = (
        "gpt-4o",
        "gpt-4.1",
        "gpt-4.5",
        "gpt-5",
        "chatgpt-4o",
        "o1",
        "o3",
        "o4-mini",
    )
    return any(p in m for p in patterns)


def _ollama_model_likely_vision(name: str) -> bool:
    m = (name or "").lower()
    keys = (
        "llava",
        "moondream",
        "vision",
        "llama3.2-vision",
        "bakllava",
        "minicpm-v",
        "cogvlm",
        "gemma3",
    )
    return any(k in m for k in keys)


def fetch_openai_vision_models_dynamic() -> List[str]:
    """Merge curated list with /v1/models when API key is set."""
    choices = list(OPENAI_VISION_MODELS_DEFAULT)
    api_key = _normalize_openai_api_key(
        getattr(shared.opts, "pc_vision_openai_api_key", "") or ""
    )
    if not api_key:
        return _dedupe_preserve_order(choices)
    base = (
        getattr(shared.opts, "pc_vision_openai_api_url", "")
        or "https://api.openai.com/v1"
    ).rstrip("/")
    try:
        req = urllib.request.Request(
            f"{base}/models",
            headers={"Authorization": f"Bearer {api_key}"},
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        ids = [
            str(m.get("id", "")).strip()
            for m in data.get("data", [])
            if m.get("id")
        ]
        dynamic = [i for i in ids if _openai_model_likely_vision(i)]
        dynamic.sort(reverse=True)
        return _dedupe_preserve_order(dynamic + choices)
    except Exception:
        return _dedupe_preserve_order(choices)


def fetch_ollama_vision_models_dynamic() -> List[str]:
    choices = list(OLLAMA_VISION_MODELS_DEFAULT)
    base = (
        getattr(shared.opts, "pc_vision_ollama_url", "") or "http://127.0.0.1:11434"
    ).rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/api/tags", timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        names = [
            str(m.get("name", "")).strip()
            for m in data.get("models", [])
            if m.get("name")
        ]
        vision = [n for n in names if _ollama_model_likely_vision(n)]
        if not vision:
            vision = names
        return _dedupe_preserve_order(vision + choices)
    except Exception:
        return _dedupe_preserve_order(choices)


def openai_vision_model_dropdown_args() -> dict:
    """Static defaults only — avoids blocking Reload UI on OpenAI API calls."""
    current = getattr(shared.opts, "pc_vision_openai_model", "gpt-4o-mini")
    return {
        "choices": _ensure_current_in_choices(
            list(OPENAI_VISION_MODELS_DEFAULT), current
        ),
    }


def gemini_vision_model_dropdown_args() -> dict:
    current = getattr(shared.opts, "pc_vision_gemini_model", "gemini-2.0-flash")
    return {
        "choices": _ensure_current_in_choices(
            list(GEMINI_VISION_MODELS_DEFAULT), current
        ),
    }


def ollama_vision_model_dropdown_args() -> dict:
    """Static defaults only — avoids blocking Reload UI on Ollama HTTP."""
    current = getattr(shared.opts, "pc_vision_ollama_model", "llava")
    return {
        "choices": _ensure_current_in_choices(
            list(OLLAMA_VISION_MODELS_DEFAULT), current
        ),
    }


def refresh_openai_vision_models() -> None:
    fetch_openai_vision_models_dynamic()


def refresh_ollama_vision_models() -> None:
    fetch_ollama_vision_models_dynamic()


def refresh_gemini_vision_models() -> None:
    pass


def get_vision_models_for_provider(provider: str) -> List[str]:
    p = normalize_provider(provider)
    if p == "openai":
        return fetch_openai_vision_models_dynamic()
    if p == "gemini":
        return list(GEMINI_VISION_MODELS_DEFAULT)
    if p == "ollama":
        return fetch_ollama_vision_models_dynamic()
    return []


def _normalize_choice(raw: str, allowed: list[str], label_map: dict[str, str], default: str) -> str:
    """Accept internal keys, Japanese labels, or broken tuple repr from Gradio 3."""
    if raw is None:
        return default
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        raw = raw[-1]
    s = str(raw).strip()
    if not s:
        return default
    low = s.lower()
    if low in allowed:
        return low
    if s in label_map:
        return label_map[s]
    # Broken: "('Ollama（ローカルLLM）', 'ollama')"
    for key in allowed:
        if f"'{key}'" in s or f'"{key}"' in s:
            return key
    for label, key in label_map.items():
        if label in s:
            return key
    return default


def normalize_focus(raw: str) -> str:
    return _normalize_choice(raw, FOCUS_CHOICES, _FOCUS_FROM_LABEL, "clothing")


def normalize_provider(raw: str) -> str:
    key = _normalize_choice(raw, PROVIDER_CHOICES, _PROVIDER_FROM_LABEL, "blip")
    if key == "blip" and raw and "chatgpt" in str(raw).lower():
        return "openai"
    return key


def normalize_language(raw: str) -> str:
    return _normalize_choice(raw, ["en", "ja"], _LANGUAGE_FROM_LABEL, "en")


def normalize_output_style(raw: str) -> str:
    return _normalize_choice(raw, STYLE_CHOICES, _STYLE_FROM_LABEL, "detailed")


def _split_comma_respecting_parens(text: str) -> List[str]:
    """Split on commas only outside (weighted:tag) groups."""
    parts: List[str] = []
    buf: List[str] = []
    depth = 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch in ",、\n;" and depth == 0:
            chunk = "".join(buf).strip().rstrip(".")
            if chunk:
                parts.append(chunk)
            buf = []
        else:
            buf.append(ch)
    tail = "".join(buf).strip().rstrip(".")
    if tail:
        parts.append(tail)
    return parts


def split_caption_to_tags(text: str, style: str = "detailed") -> List[str]:
    """
    Split prose or comma-separated caption into individual prompt tags/phrases.
    """
    raw = (text or "").strip()
    if not raw:
        return []

    # Remove trailing notes from BLIP / status hints
    raw = re.sub(
        r"\s*[（(][^）)]*(?:BLIP|Ollama|Gemini|ChatGPT|OpenAI)[^）)]*[）)]\s*",
        "",
        raw,
        flags=re.I,
    )
    raw = raw.strip()
    style = normalize_output_style(style)

    if style == "detailed":
        parts = _split_comma_respecting_parens(raw)
    else:
        parts = []
        for chunk in re.split(r"[,、\n;]+", raw):
            chunk = chunk.strip().rstrip(".")
            if chunk:
                parts.append(chunk)

    if style == "simple" and len(parts) <= 1 and parts:
        sentence = parts[0]
        subs = [s.strip().rstrip(".") for s in re.split(r"\.\s+", sentence) if s.strip()]
        if len(subs) > 1:
            parts = subs
        elif re.search(r"\s+and\s+", sentence, re.I):
            parts = [
                p.strip().rstrip(".")
                for p in re.split(r"\s+and\s+", sentence, flags=re.I)
                if p.strip()
            ]
        else:
            for sep in (
                r"\s+with\s+",
                r"\s+wearing\s+",
                r"\s+standing\s+in\s+",
                r"\s+in\s+front\s+of\s+",
            ):
                if re.search(sep, sentence, re.I):
                    parts = [
                        p.strip().rstrip(".")
                        for p in re.split(sep, sentence, flags=re.I)
                        if p.strip()
                    ]
                    break

    cleaned: List[str] = []
    seen = set()
    for p in parts:
        p = p.strip().rstrip(".")
        if style == "simple":
            p = re.sub(r"^(a|an|the)\s+", "", p, flags=re.I).strip()
        if not p or len(p) < 2:
            continue
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(p)
    return cleaned


def format_tags_comma(text: str, style: str = "detailed") -> str:
    """Gradio handler: rewrite caption as comma-separated tags/phrases."""
    style = normalize_output_style(style)
    tags = split_caption_to_tags(text, style)
    if tags:
        return ", ".join(tags)
    return (text or "").strip()


def format_tags_preview_html(text: str, style: str = "detailed") -> str:
    style = normalize_output_style(style)
    tags = split_caption_to_tags(text, style)
    if not tags:
        return (
            '<div id="pc_vision_tags_preview" class="pc-vision-tags-preview">'
            '<span class="pc-vision-tags-empty">単語がありません</span></div>'
        )
    chips = "".join(
        f'<span class="pc-vision-tag-chip">{_html_esc(t)}</span>' for t in tags
    )
    return (
        f'<div id="pc_vision_tags_preview" class="pc-vision-tags-preview">'
        f'<span class="pc-vision-tags-count">{len(tags)} フレーズ</span>{chips}</div>'
    )


def _html_esc(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


_FOCUS_PROMPTS_EN = {
    "clothing": (
        "Describe ONLY clothing, footwear, accessories, and worn items visible in the image. "
        "Include colors, materials, fit, length, patterns, and small details. "
        "Do NOT describe face, hair, body type, pose, or background. "
        "Output comma-separated English phrases suitable for Stable Diffusion prompts."
    ),
    "character": (
        "Describe the character: hair, eyes, expression, pose, body visible, and all clothing. "
        "Do NOT describe background or scenery. "
        "Output comma-separated English phrases for Stable Diffusion."
    ),
    "scene": (
        "Describe background, environment, lighting, atmosphere, and camera framing only. "
        "Do NOT describe the character or clothing. "
        "Output comma-separated English phrases for Stable Diffusion."
    ),
    "all": (
        "Describe the full image for image generation: subject, clothing, pose, "
        "background, lighting, and art style. "
        "Output comma-separated English phrases for Stable Diffusion."
    ),
}

_FOCUS_PROMPTS_DETAILED = {
    "clothing": (
        "Describe ONLY clothing, footwear, accessories, and worn items in the image. "
        "Include colors, materials, fit, length, construction details, trims, and ornaments. "
        "Do NOT describe face, hair, body, pose, or background."
    ),
    "character": (
        "Describe the character appearance: hair, eyes, expression, pose, and all clothing. "
        "Do NOT describe background."
    ),
    "scene": (
        "Describe background, environment, lighting, atmosphere, and camera framing only. "
        "Do NOT describe the character or clothing."
    ),
    "all": (
        "Describe the full image for image generation: subject, clothing, pose, "
        "background, lighting, and art style."
    ),
}


def _image_to_pil(image) -> Optional[Image.Image]:
    if image is None:
        return None
    if isinstance(image, Image.Image):
        return image.convert("RGB")
    try:
        import numpy as np

        if isinstance(image, np.ndarray):
            return Image.fromarray(image).convert("RGB")
    except Exception:
        pass
    return None


def _pil_to_base64_jpeg(pil: Image.Image, max_side: int = 1024) -> str:
    img = pil.copy()
    w, h = img.size
    if max(w, h) > max_side:
        scale = max_side / float(max(w, h))
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _build_instruction(focus: str, language: str, style: str = "detailed") -> str:
    focus = (focus or "clothing").strip().lower()
    style = normalize_output_style(style)
    if style == "detailed":
        if focus not in _FOCUS_PROMPTS_DETAILED:
            focus = "clothing"
        instr = _FOCUS_PROMPTS_DETAILED[focus] + "\n\n" + _DETAILED_FORMAT_RULES
    else:
        if focus not in _FOCUS_PROMPTS_EN:
            focus = "clothing"
        instr = _FOCUS_PROMPTS_EN[focus]
    lang = (language or "en").strip().lower()
    if lang in ("ja", "jp", "japanese", "日本語"):
        instr += " Use Japanese fragments with underscores between words."
    else:
        instr += " Write all fragments in English."
    return instr


def _caption_blip(pil: Image.Image, focus: str) -> Tuple[str, str]:
    interrogator = getattr(shared, "interrogator", None)
    if interrogator is None:
        return "", "BLIP: WebUI の Interrogate が利用できません。モデル読み込み後に再試行してください。"

    try:
        interrogator.load()
        caption = interrogator.generate_caption(pil)
        interrogator.send_blip_to_ram()
    except Exception as exc:
        return "", f"BLIP エラー: {exc}"

    caption = (caption or "").strip()
    if not caption:
        return "", "BLIP が空の結果を返しました。"

    note = ""
    if focus == "clothing":
        note = (
            "（BLIP は画像全体の短い説明です。衣装の細部には Ollama / ChatGPT / Gemini を推奨）"
        )
    return caption + note, "BLIP（ローカル・無料）で生成しました。"


def _normalize_openai_api_key(raw: str) -> str:
    """Strip common copy-paste mistakes from settings."""
    key = (raw or "").strip()
    if key.lower().startswith("bearer "):
        key = key[7:].strip()
    if (key.startswith('"') and key.endswith('"')) or (key.startswith("'") and key.endswith("'")):
        key = key[1:-1].strip()
    return key


def _friendly_api_error(service: str, code: int, body: str) -> str:
    """Short Japanese hint for common Vision API errors."""
    low = (body or "").lower()
    if code == 429 or "quota" in low or "rate" in low:
        return (
            f"{service}: 利用上限（無料枠）に達しました（HTTP 429）。"
            " しばらく待つか、別の AI（ChatGPT / Ollama / BLIP）を使ってください。"
            " 詳細: https://ai.google.dev/gemini-api/docs/rate-limits"
        )
    if code in (401, 403) or "api key" in low or "permission" in low or "invalid_api_key" in low:
        if "openai" in service.lower() or "chatgpt" in service.lower():
            return (
                f"{service}: API キーが無効です（HTTP {code}）。"
                " ChatGPT Plus / Team の月額課金だけでは API は使えません。"
                " https://platform.openai.com/api-keys で「Secret key」（sk- で始まる）を新規作成し、"
                " https://platform.openai.com/settings/organization/billing で API 用の残高・課金を有効にしてください。"
                " 設定のキー欄には sk-... のみ（Bearer 不要）。"
                " ベースURLは https://api.openai.com/v1 のまま。"
            )
        return (
            f"{service}: API キーが無効か権限がありません（HTTP {code}）。"
            " 設定のキーを確認してください。"
        )
    snippet = (body or "").strip()
    if len(snippet) > 220:
        snippet = snippet[:220] + "…"
    return f"{service} API エラー ({code}): {snippet or '不明'}"


def _http_json_post(
    url: str,
    payload: dict,
    timeout: int = 120,
    extra_headers: Optional[dict] = None,
) -> dict:
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def _caption_ollama(
    pil: Image.Image, focus: str, language: str, style: str = "detailed"
) -> Tuple[str, str]:
    base_url = (getattr(shared.opts, "pc_vision_ollama_url", "") or "http://127.0.0.1:11434").rstrip("/")
    model = (getattr(shared.opts, "pc_vision_ollama_model", "") or "llava").strip()
    if not model:
        return "", "Ollama モデル名が未設定です（設定 → Prompt Composer）。"

    b64 = _pil_to_base64_jpeg(pil)
    prompt = _build_instruction(focus, language, style)

    payload = {
        "model": model,
        "prompt": prompt,
        "images": [b64],
        "stream": False,
    }

    try:
        data = _http_json_post(f"{base_url}/api/generate", payload, timeout=180)
    except urllib.error.URLError as exc:
        return "", (
            f"Ollama に接続できません（{base_url}）。"
            f" Ollama を起動し、ビジョンモデル（例: ollama pull {model}）を用意してください。詳細: {exc}"
        )
    except Exception as exc:
        return "", f"Ollama エラー: {exc}"

    text = (data.get("response") or "").strip()
    if not text:
        return "", "Ollama が空の応答を返しました。モデルが画像入力に対応しているか確認してください。"
    return text, f"Ollama（{model}）で生成しました。"


def _caption_gemini(
    pil: Image.Image, focus: str, language: str, style: str = "detailed"
) -> Tuple[str, str]:
    api_key = (getattr(shared.opts, "pc_vision_gemini_api_key", "") or "").strip()
    if not api_key:
        return "", "Gemini API キーが未設定です（設定 → Prompt Composer → Vision）。"

    model = (getattr(shared.opts, "pc_vision_gemini_model", "") or "gemini-2.0-flash").strip()
    b64 = _pil_to_base64_jpeg(pil)
    prompt = _build_instruction(focus, language, style)

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={api_key}"
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                ]
            }
        ],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1024},
    }

    try:
        data = _http_json_post(url, payload, timeout=120)
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        return "", _friendly_api_error("Gemini", exc.code, body)
    except Exception as exc:
        return "", f"Gemini エラー: {exc}"

    try:
        parts = data["candidates"][0]["content"]["parts"]
        text = "".join(p.get("text", "") for p in parts).strip()
    except (KeyError, IndexError, TypeError):
        return "", f"Gemini の応答形式が不正です: {json.dumps(data)[:300]}"

    if not text:
        return "", "Gemini が空の応答を返しました。"
    return text, f"Gemini（{model}）で生成しました。"


def _caption_openai(
    pil: Image.Image, focus: str, language: str, style: str = "detailed"
) -> Tuple[str, str]:
    api_key = _normalize_openai_api_key(
        getattr(shared.opts, "pc_vision_openai_api_key", "") or ""
    )
    if not api_key:
        return "", "OpenAI API キーが未設定です（設定 → Prompt Composer → Vision）。"
    if not (api_key.startswith("sk-") or api_key.startswith("sess-")):
        return (
            "",
            "OpenAI API キーの形式が不正です。platform.openai.com で作成した "
            "Secret key（通常 sk- で始まる）を貼り付けてください。ChatGPT のログインパスワードではありません。",
        )

    model = (getattr(shared.opts, "pc_vision_openai_model", "") or "gpt-4o-mini").strip()
    base_url = (
        getattr(shared.opts, "pc_vision_openai_api_url", "")
        or "https://api.openai.com/v1"
    ).rstrip("/")
    b64 = _pil_to_base64_jpeg(pil)
    prompt = _build_instruction(focus, language, style)

    model_low = model.lower()
    image_detail = "high"
    if any(tag in model_low for tag in ("gpt-5.4", "gpt-5.5", "gpt-5-4", "gpt-5-5")):
        image_detail = "high"

    url = f"{base_url}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{b64}",
                            "detail": image_detail,
                        },
                    },
                ],
            }
        ],
        "temperature": 0.2,
    }
    # GPT-5 / o-series use max_completion_tokens instead of max_tokens
    if model_low.startswith(("gpt-5", "o1", "o3", "o4")):
        payload["max_completion_tokens"] = 2048
    else:
        payload["max_tokens"] = 1024

    try:
        data = _http_json_post(
            url,
            payload,
            timeout=120,
            extra_headers={"Authorization": f"Bearer {api_key}"},
        )
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        return "", _friendly_api_error("ChatGPT / OpenAI", exc.code, body)
    except Exception as exc:
        return "", f"ChatGPT / OpenAI エラー: {exc}"

    try:
        text = (data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        return "", f"OpenAI の応答形式が不正です: {json.dumps(data)[:300]}"

    if not text:
        return "", "ChatGPT が空の応答を返しました。"
    return text, f"ChatGPT（{model}）で生成しました。"


def analyze_reference_image(
    image,
    focus: str,
    provider: str,
    language: str,
    output_style: str = "detailed",
) -> Tuple[str, str]:
    """
    Gradio handler: returns (caption_text, status_html).
    """
    pil = _image_to_pil(image)
    if pil is None:
        return "", '<span class="pc-vision-status pc-vision-status-error">画像をアップロードしてください。</span>'

    focus = normalize_focus(focus)
    provider = normalize_provider(provider)
    language = normalize_language(language)
    style = normalize_output_style(output_style)

    if provider == "ollama":
        text, msg = _caption_ollama(pil, focus, language, style)
    elif provider == "gemini":
        text, msg = _caption_gemini(pil, focus, language, style)
    elif provider == "openai":
        text, msg = _caption_openai(pil, focus, language, style)
    else:
        text, msg = _caption_blip(pil, focus)
        if style == "detailed" and text:
            msg += "（BLIP は詳細形式に非対応のため ChatGPT / Gemini / Ollama 推奨）"

    if not text:
        return "", f'<span class="pc-vision-status pc-vision-status-error">{msg}</span>'

    safe_msg = msg.replace("&", "&amp;").replace("<", "&lt;")
    status = f'<span class="pc-vision-status pc-vision-status-ok">{safe_msg}</span>'
    return text, status
