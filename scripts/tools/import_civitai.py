#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Mine popular prompt tokens from Civitai and write a YAML tag dictionary.

- Fetches top images via ``GET /api/v1/images`` with multiple sort/period combos.
- Extracts comma-separated tokens from prompts, normalises them, and aggregates
  frequency across collected prompts.
- Keeps tokens appearing in at least ``--min-count`` distinct prompts.
- Joins with the Danbooru CSV (already cached) for JP translations and post-count
  tiering when a token has a Danbooru tag with the same spelling.
- Output: ``group_tags/civitai.yaml`` organised by base model (Illustrious / Pony /
  SDXL / Flux / NoobAI / Other) and frequency tier.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Tuple

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
for _p in (_SCRIPT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

USER_AGENT = "PromptComposerImporter/1.0 (personal local import)"
API_URL = "https://civitai.com/api/v1/images"
CACHE_DIR = "/tmp/pc-tag-import"

# Civitai sort/period combos to traverse (each yields up to ``pages_per_combo`` pages).
SORTS = ("Most Reactions", "Most Comments")
PERIODS = ("AllTime", "Month", "Week")
DEFAULT_LIMIT = 200  # per page
DEFAULT_PAGES = 4  # pages per combo
DEFAULT_MIN_COUNT = 5  # minimum prompt occurrences to keep

# Base-model bucketing
MODEL_BUCKETS = {
    "Illustrious": "Illustrious",
    "NoobAI": "NoobAI",
    "Pony": "Pony / SDXL Anime",
    "SDXL 1.0": "SDXL",
    "SDXL": "SDXL",
    "Flux.1 D": "Flux.1",
    "Flux.1 S": "Flux.1",
    "Flux.1 Kontext": "Flux.1",
    "SD 1.5": "SD 1.5",
    "SD 3.5": "SD 3.5",
}

# Token cleaning patterns
_LORA_RE = re.compile(r"<[^>]+>")
_WEIGHT_RE = re.compile(r"^\(+|\)+$|^\[+|\]+$")
_WEIGHT_NUM_RE = re.compile(r":\d+(\.\d+)?$")
_TOKEN_OK_RE = re.compile(r"^[a-zA-Z0-9 _\-/.'!?]+$")


def fetch_url(url: str, timeout: int = 60) -> Optional[Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


def iter_civitai_pages(
    sort: str, period: str, limit: int, pages: int, nsfw: Optional[str] = "None"
) -> List[Dict]:
    out: List[Dict] = []
    cursor = None
    for _ in range(pages):
        params = {
            "limit": str(limit),
            "sort": sort,
            "period": period,
        }
        if nsfw:
            params["nsfw"] = nsfw
        if cursor:
            params["cursor"] = cursor
        url = f"{API_URL}?{urllib.parse.urlencode(params)}"
        data = fetch_url(url)
        if not isinstance(data, dict):
            break
        items = data.get("items") or []
        if not items:
            break
        out.extend(items)
        meta = data.get("metadata") or {}
        cursor = meta.get("nextCursor")
        if not cursor:
            break
        time.sleep(0.4)
    return out


def clean_token(token: str) -> str:
    token = (token or "").strip().strip("\"'`")
    if not token:
        return ""
    # strip BREAK, parentheses, brackets and weight syntax
    token = _LORA_RE.sub("", token)
    token = token.strip()
    while token and (token.startswith("(") or token.startswith("[") or token.startswith("{")):
        token = token[1:]
    while token and (token.endswith(")") or token.endswith("]") or token.endswith("}")):
        token = token[:-1]
    token = _WEIGHT_NUM_RE.sub("", token)
    token = token.replace("\n", " ").replace("\r", "").strip()
    token = re.sub(r"\s+", " ", token)
    return token


def is_useful_token(token: str) -> bool:
    if not token:
        return False
    if len(token) < 3 or len(token) > 60:
        return False
    if token.isdigit():
        return False
    if not _TOKEN_OK_RE.match(token):
        return False
    if "http" in token.lower() or "://" in token:
        return False
    if token.lower() in {
        "break",
        "high quality",
        "lora",
        "embedding",
        "deepnegative",
        "ng_deepnegative_v1_75t",
        "easynegative",
        "and",
        "an",
        "with",
        "of",
        "the",
        "very",
    }:
        return False
    return True


def collect_prompts(items: List[Dict]) -> List[Tuple[str, str]]:
    """Return list of (prompt, base_model) tuples."""
    out: List[Tuple[str, str]] = []
    for it in items:
        meta = it.get("meta") or {}
        prompt = (meta.get("prompt") or "").strip()
        if not prompt:
            continue
        base = (it.get("baseModel") or meta.get("Model") or "").strip()
        out.append((prompt, base))
    return out


def tokens_from_prompt(prompt: str) -> List[str]:
    parts = prompt.replace("BREAK", ",").split(",")
    out: List[str] = []
    for p in parts:
        t = clean_token(p)
        if not t:
            continue
        if is_useful_token(t):
            out.append(t.lower())
    return out


def load_danbooru_csv(path: str) -> Dict[str, Tuple[int, int]]:
    """Return {tag: (type, count)} keyed by tag (lowercased, underscored)."""
    out: Dict[str, Tuple[int, int]] = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 3:
                continue
            try:
                tag = row[0].strip().lower()
                typ = int(row[1])
                cnt = int(row[2])
            except ValueError:
                continue
            if tag:
                out[tag] = (typ, cnt)
    return out


def load_jp(path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not os.path.isfile(path):
        return out
    with open(path, encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) >= 2:
                out[row[0].strip().lower()] = row[1].strip()
    return out


def normalize_for_lookup(token: str) -> str:
    """Match Civitai-style tokens against Danbooru tags."""
    return token.lower().replace(" ", "_")


def freq_tier(count: int) -> str:
    if count >= 100:
        return "★★★ 超頻出 (100+)"
    if count >= 20:
        return "★★ 頻出 (20-100)"
    if count >= 5:
        return "★ 出現 (5-20)"
    return "★ 出現 (5-20)"


def build_yaml(
    freq_by_model: Dict[str, Counter],
    danbooru: Dict[str, Tuple[int, int]],
    jp_hand: Dict[str, str],
    jp_machine: Dict[str, str],
    min_count: int,
) -> List[Dict]:
    sections: Dict[str, Dict] = {}
    for model, counter in freq_by_model.items():
        sec = sections.setdefault(model, {"name": f"Civitai 人気プロンプト ({model})", "_cats": {}})
        for token, count in counter.most_common():
            if count < min_count:
                break
            tier = freq_tier(count)
            tier_cat = sec["_cats"].setdefault(tier, {"name": tier, "_groups": {}})
            # Normalise display form: prefer Danbooru spelling if matched
            lookup = normalize_for_lookup(token)
            display = lookup if lookup in danbooru else token
            jp = jp_hand.get(lookup) or jp_machine.get(lookup) or ""
            db_info = danbooru.get(lookup)
            type_label = "general"
            if db_info:
                type_label = {
                    0: "一般",
                    1: "絵師",
                    3: "作品",
                    4: "キャラ",
                    5: "メタ",
                }.get(db_info[0], "その他")
            grp = tier_cat["_groups"].setdefault(type_label, {"name": type_label, "tags": {}})
            grp["tags"][display] = jp or display

    out: List[Dict] = []
    model_order = ["Illustrious", "NoobAI", "Pony / SDXL Anime", "SDXL", "Flux.1", "SD 1.5", "SD 3.5", "Other"]
    for model in model_order:
        sec = sections.get(model)
        if not sec:
            continue
        cats = []
        tier_order = ["★★★ 超頻出 (100+)", "★★ 頻出 (20-100)", "★ 出現 (5-20)"]
        for tier in tier_order:
            cat = sec["_cats"].get(tier)
            if not cat:
                continue
            groups = []
            group_order = ["一般", "キャラ", "作品", "メタ", "絵師", "その他", "general"]
            for gname in group_order:
                g = cat["_groups"].get(gname)
                if not g:
                    continue
                g["tags"] = dict(sorted(g["tags"].items(), key=lambda kv: kv[0].lower()))
                groups.append(g)
            if groups:
                cats.append({"name": tier, "groups": groups})
        if cats:
            out.append({"name": sec["name"], "categories": cats})
    return out


def map_base_model(base: str) -> str:
    if not base:
        return "Other"
    for key, bucket in MODEL_BUCKETS.items():
        if base.startswith(key):
            return bucket
    return "Other"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=os.path.join(_SCRIPT_DIR, "..", "group_tags", "civitai.yaml"))
    parser.add_argument("--pages", type=int, default=DEFAULT_PAGES, help="Pages per sort/period combo")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Items per page (max 200)")
    parser.add_argument("--min-count", type=int, default=DEFAULT_MIN_COUNT)
    parser.add_argument("--sfw-only", action="store_true", help="Only fetch SFW (nsfw=None means no filter)")
    parser.add_argument("--cache", default=CACHE_DIR)
    args = parser.parse_args()

    cache_file = os.path.join(args.cache, "civitai-items.json")
    os.makedirs(args.cache, exist_ok=True)

    items: List[Dict] = []
    if os.path.isfile(cache_file):
        with open(cache_file, encoding="utf-8") as f:
            items = json.load(f) or []
        print(f"[civitai-import] loaded {len(items)} cached items")
    else:
        for sort in SORTS:
            for period in PERIODS:
                nsfw = "False" if args.sfw_only else "None"
                fetched = iter_civitai_pages(sort, period, args.limit, args.pages, nsfw=nsfw)
                items.extend(fetched)
                print(f"[civitai-import] {sort}/{period}: +{len(fetched)} (total={len(items)})")
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(items, f)

    prompts = collect_prompts(items)
    print(f"[civitai-import] prompts with text: {len(prompts)}")

    freq_by_model: Dict[str, Counter] = defaultdict(Counter)
    for prompt, base in prompts:
        bucket = map_base_model(base)
        tokens = set(tokens_from_prompt(prompt))
        for t in tokens:
            freq_by_model[bucket][t] += 1

    for model, c in freq_by_model.items():
        print(f"  {model}: {len(c)} unique tokens, top: {c.most_common(3)}")

    db_path = os.path.join(args.cache, "danbooru.csv")
    jp_hand_path = os.path.join(args.cache, "danbooru-jp.csv")
    jp_mach_path = os.path.join(args.cache, "danbooru-machine-jp.csv")
    danbooru = load_danbooru_csv(db_path)
    jp_hand = load_jp(jp_hand_path)
    jp_mach = load_jp(jp_mach_path)
    print(f"[civitai-import] danbooru lookup: {len(danbooru)} jp_hand={len(jp_hand)} jp_machine={len(jp_mach)}")

    data = build_yaml(freq_by_model, danbooru, jp_hand, jp_mach, args.min_count)

    total = 0
    for s in data:
        for c in s.get("categories") or []:
            for g in c.get("groups") or []:
                total += len(g.get("tags") or {})
    print(f"[civitai-import] selected tags: {total}")

    out_path = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(
            data,
            f,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=120,
        )
    print(f"[civitai-import] wrote: {out_path}")


if __name__ == "__main__":
    main()
