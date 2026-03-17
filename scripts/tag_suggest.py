""" -*- coding: UTF-8 -*-
Tag suggestion backend for Prompt Composer.
Loads tags from sd-prompt-composer/tags/*.csv and
provides simple substring-based suggestions.

This is intentionally independent of a1111-sd-webui-tagcomplete so that
replacing the CSV files in extensions/sd-prompt-composer/tags will
immediately change the suggestions.
"""

import csv
import os
from typing import List, Dict, Optional, Tuple

_loaded = False
_tags: List[Dict[str, str]] = []


def _load_translations(path: str, translations: Dict[str, str]) -> None:
    """Load a *_translations_*.csv file into translations dict."""
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                # 英語タグ側も余分な二重引用符を除去して正規化
                tag = (row[0] or "").strip().strip('"')
                if not tag or tag.startswith("#"):
                    continue
                # Use the first translation column as JP label when available
                jp = ""
                if len(row) > 1:
                    jp = (row[1] or "").strip().strip('"')
                translations[tag] = jp
    except Exception:
        return


def _load_tags_with_freq(path: str, tags: List[Dict[str, str]], translations: Dict[str, str]) -> None:
    """Load a tag frequency CSV (e.g. danbooru.csv) into tags list."""
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            reader = csv.reader(f)
            for row in reader:
                if not row:
                    continue
                tag = (row[0] or "").strip()
                if not tag or tag.startswith("#"):
                    continue
                freq = 0
                if len(row) > 2:
                    try:
                        freq = int(row[2])
                    except ValueError:
                        freq = 0
                entry: Dict[str, str] = {"tag": tag, "freq": freq}
                jp = translations.get(tag)
                if jp:
                    entry["jp"] = jp
                tags.append(entry)
    except Exception:
        return


def _find_tagcomplete_tags_dir(extension_dir: str) -> Optional[str]:
    """
    Try to locate a1111-sd-webui-tagcomplete/tags directory.
    We intentionally avoid importing tagcomplete Python modules (they may fail on Forge),
    and instead resolve the path relative to this extension's directory.
    """
    # Expected structure:
    #   <webui_root>/extensions/sd-prompt-composer
    #   <webui_root>/extensions/a1111-sd-webui-tagcomplete/tags
    parent = os.path.abspath(os.path.join(extension_dir, os.pardir))
    candidate = os.path.join(parent, "a1111-sd-webui-tagcomplete", "tags")
    if os.path.isdir(candidate):
        return candidate
    return None


def _list_csv_files(dir_path: str) -> List[str]:
    try:
        names = os.listdir(dir_path)
    except Exception:
        return []
    out: List[str] = []
    for name in names:
        lower = name.lower()
        if not lower.endswith(".csv"):
            continue
        out.append(os.path.join(dir_path, name))
    return out


def _partition_translation_and_tag_csvs(csv_paths: List[str]) -> Tuple[List[str], List[str]]:
    """
    Tagcomplete supports a separate translation CSV option; file naming varies.
    We'll use a best-effort heuristic:
      - filenames containing 'translation' are treated as translation sources
      - everything else is treated as a tag list source
    """
    translations: List[str] = []
    taglists: List[str] = []
    for p in csv_paths:
        base = os.path.basename(p).lower()
        if "translation" in base:
            translations.append(p)
        else:
            taglists.append(p)
    return translations, taglists


def init(extension_dir: str) -> None:
    """Initialize by loading CSV files from this extension's tags directory."""
    global _loaded, _tags
    if _loaded:
        return

    # We prefer reading from a1111-sd-webui-tagcomplete's tags directory if present,
    # because it already contains popular tag corpuses (danbooru, e621, etc.).
    local_tags_dir = os.path.join(extension_dir, "tags")
    tagcomplete_tags_dir = _find_tagcomplete_tags_dir(extension_dir)

    translations: Dict[str, str] = {}
    tag_entries: Dict[str, Dict[str, str]] = {}  # tag -> {"tag": str, "freq": int, "jp"?: str}

    def merge_entries(entries: List[Dict[str, str]]) -> None:
        for e in entries:
            tag = (e.get("tag") or "").strip()
            if not tag:
                continue
            freq = int(e.get("freq", 0) or 0)
            jp = (e.get("jp") or "").strip()
            cur = tag_entries.get(tag)
            if cur is None:
                cur = {"tag": tag, "freq": freq}
                if jp:
                    cur["jp"] = jp
                tag_entries[tag] = cur
                continue
            # Prefer higher frequency if both provide it
            try:
                cur_freq = int(cur.get("freq", 0) or 0)
            except Exception:
                cur_freq = 0
            if freq > cur_freq:
                cur["freq"] = freq
            # Prefer keeping any JP translation if available
            if jp and not cur.get("jp"):
                cur["jp"] = jp

    # Load translation CSVs (tagcomplete first, then local) so local can override if needed.
    for dir_path in [tagcomplete_tags_dir, local_tags_dir]:
        if not dir_path or not os.path.isdir(dir_path):
            continue
        csvs = _list_csv_files(dir_path)
        translation_csvs, _ = _partition_translation_and_tag_csvs(csvs)
        for p in translation_csvs:
            _load_translations(p, translations)

    # Load taglist CSVs (tagcomplete first, then local). Apply translations map during load.
    for dir_path in [tagcomplete_tags_dir, local_tags_dir]:
        if not dir_path or not os.path.isdir(dir_path):
            continue
        csvs = _list_csv_files(dir_path)
        _, tag_csvs = _partition_translation_and_tag_csvs(csvs)
        for p in tag_csvs:
            loaded: List[Dict[str, str]] = []
            _load_tags_with_freq(p, loaded, translations)
            merge_entries(loaded)

    # If we only have translations and no main CSVs, fall back to them directly
    if not tag_entries and translations:
        for tag, jp in translations.items():
            if not tag:
                continue
            entry: Dict[str, str] = {"tag": tag, "freq": 0}
            if jp:
                entry["jp"] = jp
            tag_entries[tag] = entry

    # Sort once by frequency descending so that more common tags come first
    tags_list: List[Dict[str, str]] = list(tag_entries.values())
    tags_list.sort(key=lambda t: int(t.get("freq", 0) or 0), reverse=True)

    _tags = tags_list
    _loaded = True

    # Minimal startup logging (helps diagnose source issues)
    src = "tagcomplete+local" if tagcomplete_tags_dir else "local"
    print(f"[Prompt Composer] TagSuggest loaded {len(_tags)} tags (source={src})")


def suggest(query: str, limit: int = 30) -> List[Dict[str, str]]:
    """Return up to `limit` tag suggestions matching the query."""
    if not _loaded or not _tags:
        return []

    q = (query or "").strip().lower()
    if not q:
        return []

    results: List[Dict[str, str]] = []
    # Prefer prefix matches, but allow substring matches as fallback
    for item in _tags:
        tag = item["tag"]
        tl = tag.lower()
        if tl.startswith(q) or (len(q) >= 2 and q in tl):
            res: Dict[str, str] = {"tag": tag}
            jp = item.get("jp")
            if jp:
                res["jp"] = jp
            results.append(res)
        if len(results) >= limit:
            break
    return results

