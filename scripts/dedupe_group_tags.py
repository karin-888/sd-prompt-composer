#!/usr/bin/env python3
"""Remove duplicate tag entries from group_tags/*.yaml (keep one per tag string)."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Set, Tuple

import yaml

import tag_dictionary
import user_storage

TagLoc = Tuple[int, int, int, str]  # section, category, group, yaml_key
Winner = Tuple[int, TagLoc]


def _scan_preview_tags(previews_dir: str) -> Set[str]:
    if not previews_dir or not os.path.isdir(previews_dir):
        return set()
    found: Set[str] = set()
    for fname in os.listdir(previews_dir):
        if fname.startswith("."):
            continue
        base, ext = os.path.splitext(fname)
        if ext.lower() in tag_dictionary._PREVIEW_EXTS:
            found.add(base)
    return found


def _tag_score(tag_key: str, tag_val: Any, preview_tags: Set[str]) -> int:
    eng = str(tag_key).strip()
    score = 0
    if eng in preview_tags:
        score += 1000
    if isinstance(tag_val, dict):
        if str(tag_val.get("preview") or "").strip():
            score += 500
        jp = str(tag_val.get("jp") or tag_val.get("label") or "")
    else:
        jp = str(tag_val or "")
    score += min(len(jp), 200)
    return score


def _collect_locations(data: list) -> Dict[str, List[Tuple[int, TagLoc, Any]]]:
    by_key: Dict[str, List[Tuple[int, TagLoc, Any]]] = {}
    for si, section in enumerate(data):
        for ci, cat in enumerate(section.get("categories", []) or []):
            for gi, group in enumerate(cat.get("groups", []) or []):
                tags = group.get("tags") or {}
                for key, val in tags.items():
                    k = str(key).strip().lower()
                    if not k:
                        continue
                    loc: TagLoc = (si, ci, gi, str(key))
                    by_key.setdefault(k, []).append((_tag_score(str(key), val, _preview_tags), loc, val))
    return by_key


def _pick_winners(
    by_key: Dict[str, List[Tuple[int, TagLoc, Any]]],
    blocked: Set[str] | None = None,
) -> Dict[str, Winner]:
    blocked = blocked or set()
    winners: Dict[str, Winner] = {}
    for k, entries in by_key.items():
        if k in blocked:
            continue
        best_score = -1
        best_loc: TagLoc | None = None
        for score, loc, _val in entries:
            if score > best_score:
                best_score = score
                best_loc = loc
        if best_loc is not None:
            winners[k] = (best_score, best_loc)
    return winners


def _remove_non_winners(data: list, winners: Dict[str, Winner]) -> int:
    keep_locs = {w[1] for w in winners.values()}
    removed = 0
    for si, section in enumerate(data):
        for ci, cat in enumerate(section.get("categories", []) or []):
            for gi, group in enumerate(cat.get("groups", []) or []):
                tags = group.get("tags") or {}
                for key in list(tags.keys()):
                    loc: TagLoc = (si, ci, gi, str(key))
                    if loc not in keep_locs:
                        del tags[key]
                        removed += 1
    return removed


def _prune_empty(data: list) -> None:
    for section in data:
        cats = section.get("categories") or []
        kept_cats = []
        for cat in cats:
            kept_groups = []
            for group in cat.get("groups", []) or []:
                if group.get("tags"):
                    kept_groups.append(group)
            if kept_groups:
                cat["groups"] = kept_groups
                kept_cats.append(cat)
        section["categories"] = kept_cats


def _load_yaml(path: str) -> list:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def _save_yaml(path: str, data: list) -> None:
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(
            data,
            f,
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
            width=120,
        )


def dedupe_file(path: str, blocked: Set[str] | None = None) -> Tuple[int, Set[str]]:
    data = _load_yaml(path)
    by_key = _collect_locations(data)
    winners = _pick_winners(by_key, blocked=blocked)
    removed = _remove_non_winners(data, winners)
    _prune_empty(data)
    _save_yaml(path, data)
    return removed, set(winners.keys())


_preview_tags: Set[str] = set()


def main() -> int:
    parser = argparse.ArgumentParser(description="Deduplicate group_tags YAML files.")
    parser.add_argument(
        "--extension-dir",
        default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    args = parser.parse_args()
    ext = os.path.abspath(args.extension_dir)

    global _preview_tags
    _preview_tags = _scan_preview_tags(user_storage.tag_previews_dir(ext))

    default_path = os.path.join(ext, "group_tags", "default.yaml")
    ai_path = os.path.join(ext, "group_tags", "ai_nante.yaml")

    if not os.path.isfile(default_path):
        print(f"Missing {default_path}", file=sys.stderr)
        return 1

    default_removed, default_keys = dedupe_file(default_path)
    print(f"default.yaml: removed {default_removed} duplicates, kept {len(default_keys)} unique tags")

    ai_removed = 0
    if os.path.isfile(ai_path):
        ai_removed, ai_keys = dedupe_file(ai_path, blocked=default_keys)
        print(
            f"ai_nante.yaml: removed {ai_removed} duplicates "
            f"(incl. overlap with default), kept {len(ai_keys)} unique tags"
        )

    # Verify via loader
    tag_dictionary.init(ext)
    print(f"Loader reports {len(tag_dictionary._tags)} tags after dedupe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
