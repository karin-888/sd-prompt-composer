""" -*- coding: UTF-8 -*-
User JSON paths under WebUI data_path (persists across extension reinstall / git pull).

Legacy location: extension_dir/data/<file> (one-time copy when the new path has no file yet).
"""

import json
import os
import shutil

USER_SUBDIR = "sd-prompt-composer"


def _legacy_path(extension_dir: str, filename: str) -> str:
    return os.path.join(extension_dir, "data", filename)


def user_root_dir():
    try:
        from modules.paths_internal import data_path

        return os.path.join(data_path, USER_SUBDIR)
    except Exception:
        return None


def bootstrap_json(extension_dir: str, filename: str, *, default_factory=None):
    """
    Return absolute path to JSON storage for this extension.

    Uses ``{data_path}/sd-prompt-composer/{filename}`` when WebUI paths are available.
    If that file is missing and the legacy extension ``data/`` file exists, copies once.
    If still missing and ``default_factory`` is set, creates the file.
    """
    root = user_root_dir()
    legacy = _legacy_path(extension_dir, filename)

    if not root:
        os.makedirs(os.path.dirname(legacy), exist_ok=True)
        if not os.path.isfile(legacy) and default_factory is not None:
            with open(legacy, "w", encoding="utf-8") as f:
                json.dump(default_factory(), f, ensure_ascii=False, indent=2)
        return legacy

    os.makedirs(root, exist_ok=True)
    dest = os.path.join(root, filename)

    if os.path.isfile(dest):
        return dest

    if os.path.isfile(legacy):
        try:
            shutil.copy2(legacy, dest)
            print(
                f"[Prompt Composer] Migrated {filename} under WebUI data directory (survives extension updates): {dest}"
            )
        except OSError as e:
            print(f"[Prompt Composer] Could not migrate {filename}: {e}")

    if not os.path.isfile(dest) and default_factory is not None:
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(default_factory(), f, ensure_ascii=False, indent=2)

    return dest


def tag_previews_dir(extension_dir: str) -> str:
    """Directory for tag dictionary preview images (filename = tag name)."""
    root = user_root_dir()
    if root:
        path = os.path.join(root, "tag-previews")
    else:
        path = os.path.join(extension_dir, "data", "tag-previews")
    os.makedirs(path, exist_ok=True)
    readme = os.path.join(path, "Put tag preview images here.txt")
    if not os.path.isfile(readme):
        try:
            with open(readme, "w", encoding="utf-8") as f:
                f.write(
                    "Tag Dictionary preview images\n"
                    "=============================\n"
                    "Place image files here. The filename (without extension) must match the tag name exactly.\n"
                    "\n"
                    "Examples:\n"
                    "  goatee.webp\n"
                    "  beard, facial hair.png\n"
                    "\n"
                    "Supported: .webp .png .jpg .jpeg .gif\n"
                    "\n"
                    "Optional YAML override (group_tags/default.yaml):\n"
                    "  goatee:\n"
                    "    jp: goatee\n"
                    "    preview: goatee.webp\n"
                )
        except OSError:
            pass
    return path
