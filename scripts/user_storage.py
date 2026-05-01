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
