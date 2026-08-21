#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".workspace"
BUILD_DIR = STATE_DIR / "build"
INSTALL_DIR = STATE_DIR / "install"
LOG_DIR = STATE_DIR / "log"
VENDOR_DIR = STATE_DIR / "vendor"
CACHE_DIR = STATE_DIR / "cache"
COMPILE_COMMANDS = STATE_DIR / "compile_commands.json"
STAMP_FILE = CACHE_DIR / "layout.json"
LAYOUT_VERSION = 2

LEGACY_BUILD = ROOT / "build"
LEGACY_INSTALL = ROOT / "install"
LEGACY_LOG = ROOT / "log"
LEGACY_VENDOR = ROOT / "vendor"
LEGACY_CACHE = ROOT / ".cache"
LEGACY_COMPILE_COMMANDS = ROOT / "compile_commands.json"


def say(message=""):
    print(message)


def die(message):
    raise SystemExit(f"[FAIL] {message}")


def _remove_generated(path: Path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


def _move_vendor_safely():
    if not LEGACY_VENDOR.exists():
        return False

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    if VENDOR_DIR.exists():
        legacy_items = list(LEGACY_VENDOR.iterdir()) if LEGACY_VENDOR.is_dir() else []
        target_items = list(VENDOR_DIR.iterdir()) if VENDOR_DIR.is_dir() else []

        if legacy_items and target_items:
            die(
                "both vendor/ and .workspace/vendor/ contain data. "
                "Automation refuses to merge them automatically."
            )

        if not target_items:
            _remove_generated(VENDOR_DIR)
        elif not legacy_items:
            _remove_generated(LEGACY_VENDOR)
            return True

    shutil.move(str(LEGACY_VENDOR), str(VENDOR_DIR))
    say("[OK] migrated vendor/ -> .workspace/vendor/")
    return True


def migrate():
    """Safely migrate the old root-level generated layout to .workspace/."""
    changed = False
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    # Vendor sources may be expensive to download and may contain useful git state,
    # so preserve them by moving the directory rather than deleting it.
    changed |= _move_vendor_safely()

    # These paths are reproducible build/cache artifacts. Moving them is unsafe
    # because generated setup files can embed their old absolute prefixes, so a
    # clean rebuild is the deterministic migration strategy.
    for path in (LEGACY_BUILD, LEGACY_INSTALL, LEGACY_LOG, LEGACY_CACHE):
        if path.exists() or path.is_symlink():
            _remove_generated(path)
            say(f"[OK] removed legacy generated path: {path.name}/")
            changed = True

    if LEGACY_COMPILE_COMMANDS.exists() or LEGACY_COMPILE_COMMANDS.is_symlink():
        _remove_generated(LEGACY_COMPILE_COMMANDS)
        say("[OK] removed legacy compile_commands.json")
        changed = True

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    STAMP_FILE.write_text(
        json.dumps({"layout_version": LAYOUT_VERSION}, indent=2) + "\n",
        encoding="utf-8",
    )

    if changed:
        say("[OK] workspace layout migrated; generated files will rebuild on demand")


def ensure():
    migrate()
    for path in (BUILD_DIR, INSTALL_DIR, LOG_DIR, VENDOR_DIR, CACHE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def status():
    say(f"workspace={STATE_DIR.relative_to(ROOT)}/")
    say(f"build={BUILD_DIR.relative_to(ROOT)}/")
    say(f"install={INSTALL_DIR.relative_to(ROOT)}/")
    say(f"log={LOG_DIR.relative_to(ROOT)}/")
    say(f"vendor={VENDOR_DIR.relative_to(ROOT)}/")
    say(f"cache={CACHE_DIR.relative_to(ROOT)}/")
    say(f"compile_commands={COMPILE_COMMANDS.relative_to(ROOT)}")

    legacy = [
        path.name
        for path in (
            LEGACY_BUILD,
            LEGACY_INSTALL,
            LEGACY_LOG,
            LEGACY_VENDOR,
            LEGACY_CACHE,
            LEGACY_COMPILE_COMMANDS,
        )
        if path.exists() or path.is_symlink()
    ]
    if legacy:
        say("[WARN] legacy root paths remain: " + ", ".join(legacy))
    else:
        say("[OK] repository root is clean")


def main():
    parser = argparse.ArgumentParser(description="Managed repository workspace layout")
    parser.add_argument("--migrate", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    if args.migrate:
        migrate()
    else:
        ensure()

    if args.status:
        status()


if __name__ == "__main__":
    main()
