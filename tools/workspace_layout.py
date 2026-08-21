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
RUNTIME_DIR = STATE_DIR / "runtime"
COMPILE_COMMANDS = STATE_DIR / "compile_commands.json"
STAMP_FILE = CACHE_DIR / "layout.json"
LAYOUT_VERSION = 3

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


def _move_directory_safely(source: Path, target: Path, label: str):
    if not source.exists():
        return False

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    if not source.is_dir():
        die(f"legacy {source.name} exists but is not a directory")

    if target.exists():
        if not target.is_dir():
            die(f"managed target {target.relative_to(ROOT)} is not a directory")

        source_items = list(source.iterdir())
        target_items = list(target.iterdir())

        if source_items and target_items:
            die(
                f"both {source.relative_to(ROOT)}/ and {target.relative_to(ROOT)}/ contain data. "
                "Automation refuses to merge them automatically."
            )

        if not target_items:
            target.rmdir()
        elif not source_items:
            source.rmdir()
            return True

    shutil.move(str(source), str(target))
    say(f"[OK] migrated {source.relative_to(ROOT)}/ -> {target.relative_to(ROOT)}/")
    return True


def migrate():
    """Safely migrate the old root-level generated layout to .workspace/."""
    changed = False
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    # Preserve non-generated state. These directories can contain fetched source,
    # version metadata, or user-inspected files, so never delete them implicitly.
    changed |= _move_directory_safely(LEGACY_VENDOR, VENDOR_DIR, "vendor")
    changed |= _move_directory_safely(LEGACY_CACHE, CACHE_DIR, "cache")

    # Build/install/log contain absolute paths and are reproducible. Reusing them
    # after a prefix move is less safe than rebuilding deterministically.
    for path in (LEGACY_BUILD, LEGACY_INSTALL, LEGACY_LOG):
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
    for path in (BUILD_DIR, INSTALL_DIR, LOG_DIR, VENDOR_DIR, CACHE_DIR, RUNTIME_DIR):
        path.mkdir(parents=True, exist_ok=True)


def status():
    say(f"workspace={STATE_DIR.relative_to(ROOT)}/")
    say(f"build={BUILD_DIR.relative_to(ROOT)}/")
    say(f"install={INSTALL_DIR.relative_to(ROOT)}/")
    say(f"log={LOG_DIR.relative_to(ROOT)}/")
    say(f"vendor={VENDOR_DIR.relative_to(ROOT)}/")
    say(f"cache={CACHE_DIR.relative_to(ROOT)}/")
    say(f"runtime={RUNTIME_DIR.relative_to(ROOT)}/")
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
