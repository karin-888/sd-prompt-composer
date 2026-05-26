# -*- coding: UTF-8 -*-
"""
Import manually collected tag dictionary data (prompt + JP + image).

Folder layout (recommended):
  my-import/
    tags.json          … metadata (see template below)
    images/            … preview images referenced from tags.json
      duck lips.jpg
      kissable lips.png

Usage:
  python import_manual_tags.py /path/to/my-import
  python import_manual_tags.py /path/to/my-import --source-name my-site
  python import_manual_tags.py /path/to/my-import --dry-run

tags.json template:
{
  "name": "my-site",
  "categories": [
    {
      "name": "記事タイトル（サイト名など）",
      "url": "https://example.com/article/  (optional)",
      "groups": [
        {
          "name": "グループ名",
          "tags": [
            {
              "tag": "duck lips",
              "jp": "アヒル口の美少女",
              "image": "duck lips.jpg"
            },
            {
              "tag": "kissable lips",
              "jp": "キス待ち",
              "image": "images/kissable lips.png"
            }
          ]
        }
      ]
    }
  ]
}

Writes:
  group_tags/{name}.yaml
  {data_path}/sd-prompt-composer/tag-previews/{tag}.{ext}
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from typing import Any, Dict, List, Optional

import yaml

_TOOLS_DIR = os.path.dirname(os.path.abspath(__file__))
_SCRIPT_DIR = os.path.dirname(_TOOLS_DIR)
for _p in (_SCRIPT_DIR, _TOOLS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import preview_filenames
import preview_convert
import user_storage

_PREVIEW_EXTS = (".webp", ".png", ".jpg", ".jpeg", ".gif")


def extension_dir() -> str:
    return os.path.dirname(_SCRIPT_DIR)


def _slugify(name: str) -> str:
    s = re.sub(r"[^\w\-]+", "_", (name or "").strip(), flags=re.UNICODE)
    return s.strip("_").lower() or "manual"


def _load_json(path: str) -> Dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("tags.json root must be an object")
    return data


def _resolve_image_path(import_dir: str, image_ref: str) -> Optional[str]:
    ref = (image_ref or "").strip()
    if not ref:
        return None
    if os.path.isabs(ref) and os.path.isfile(ref):
        return ref
    for base in (import_dir, os.path.join(import_dir, "images")):
        candidate = os.path.join(base, ref)
        if os.path.isfile(candidate):
            return candidate
    return None


def _copy_preview(src: str, tag: str, previews_dir: str, dry_run: bool) -> Optional[str]:
    dest = preview_filenames.preview_path_for_tag(previews_dir, tag, ".webp")
    if dry_run:
        return os.path.basename(dest)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.isfile(dest):
        os.remove(dest)
    ext = os.path.splitext(src)[1].lower()
    if ext == ".webp":
        shutil.copy2(src, dest)
    else:
        preview_convert.save_image_as_webp(src, dest)
    return os.path.basename(dest)


def _normalize_tag_entry(raw: Any) -> Optional[Dict[str, str]]:
    if isinstance(raw, str):
        tag = raw.strip()
        if not tag:
            return None
        return {"tag": tag, "jp": tag, "image": ""}
    if not isinstance(raw, dict):
        return None
    tag = str(raw.get("tag") or raw.get("prompt") or raw.get("en") or "").strip()
    if not tag:
        return None
    jp = str(raw.get("jp") or raw.get("ja") or raw.get("label") or "").strip()
    image = str(raw.get("image") or raw.get("preview") or raw.get("image_file") or "").strip()
    return {"tag": tag, "jp": jp or tag, "image": image}


def build_yaml(data: Dict, source_name: str) -> List[Dict]:
    section_name = (data.get("name") or source_name or "manual").strip()
    categories_out: List[Dict] = []
    for cat in data.get("categories") or []:
        if not isinstance(cat, dict):
            continue
        cat_name = str(cat.get("name") or "未分類").strip()
        groups_out: List[Dict] = []
        for grp in cat.get("groups") or []:
            if not isinstance(grp, dict):
                continue
            group_name = str(grp.get("name") or "一覧").strip()
            tags_out: Dict[str, Any] = {}
            for raw_tag in grp.get("tags") or []:
                entry = _normalize_tag_entry(raw_tag)
                if not entry:
                    continue
                tag = entry["tag"]
                jp = entry["jp"]
                preview_name = entry.get("preview_file") or ""
                if preview_name:
                    tags_out[tag] = {"jp": jp, "preview": preview_name}
                else:
                    tags_out[tag] = jp
            if tags_out:
                groups_out.append(
                    {
                        "name": group_name,
                        "tags": dict(sorted(tags_out.items(), key=lambda kv: kv[0].lower())),
                    }
                )
        if groups_out:
            categories_out.append({"name": cat_name, "groups": groups_out})
    return [{"name": section_name, "categories": categories_out}]


def run_import(import_dir: str, source_name: str = "", dry_run: bool = False) -> Dict:
    import_dir = os.path.abspath(import_dir)
    json_path = os.path.join(import_dir, "tags.json")
    if not os.path.isfile(json_path):
        raise FileNotFoundError(f"tags.json not found in {import_dir}")

    data = _load_json(json_path)
    source_name = source_name or str(data.get("name") or "").strip() or _slugify(os.path.basename(import_dir))
    data["name"] = source_name

    ext_dir = extension_dir()
    previews_dir = user_storage.tag_previews_dir(ext_dir)
    yaml_path = os.path.join(ext_dir, "group_tags", f"{_slugify(source_name)}.yaml")

    copied = 0
    missing_images: List[str] = []
    tag_count = 0

    for cat in data.get("categories") or []:
        for grp in (cat.get("groups") or [] if isinstance(cat, dict) else []):
            for raw_tag in grp.get("tags") or []:
                entry = _normalize_tag_entry(raw_tag)
                if not entry or not isinstance(raw_tag, dict):
                    continue
                tag_count += 1
                image_ref = entry.get("image") or ""
                if not image_ref:
                    continue
                src = _resolve_image_path(import_dir, image_ref)
                if not src:
                    missing_images.append(f"{entry['tag']} -> {image_ref}")
                    continue
                preview_file = _copy_preview(src, entry["tag"], previews_dir, dry_run)
                if preview_file:
                    raw_tag["preview_file"] = preview_file
                    copied += 1

    yaml_data = build_yaml(data, source_name)
    if not dry_run:
        os.makedirs(os.path.dirname(yaml_path), exist_ok=True)
        with open(yaml_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                yaml_data,
                f,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=120,
            )

    summary = {
        "source": source_name,
        "tags": tag_count,
        "images_copied": copied,
        "images_missing": len(missing_images),
        "yaml_path": yaml_path,
        "previews_dir": previews_dir,
        "dry_run": dry_run,
    }
    if missing_images:
        summary["missing"] = missing_images[:20]
    print("[manual import]", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Import manually collected tags + preview images")
    parser.add_argument("import_dir", help="Folder containing tags.json and images/")
    parser.add_argument("--source-name", default="", help="YAML section name (default: from tags.json or folder name)")
    parser.add_argument("--dry-run", action="store_true", help="Validate only; do not write files")
    args = parser.parse_args()
    try:
        run_import(args.import_dir, source_name=args.source_name, dry_run=args.dry_run)
    except Exception as e:
        print(f"[manual import] error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
