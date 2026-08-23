#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "simulation" / "scenarios.json"
STATE_DIR = ROOT / ".workspace" / "runtime"
SELECTED = STATE_DIR / "scenario.txt"
PX4_STATE = STATE_DIR / "px4.json"


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] {message}")


def load_config() -> dict:
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid scenario configuration: {exc}")
    if not isinstance(data.get("scenarios"), dict) or not data["scenarios"]:
        fail("scenario configuration has no scenarios")
    if data.get("default") not in data["scenarios"]:
        fail("default scenario is not declared")
    return data


def worlds_dir(config: dict) -> Path:
    return (ROOT / config.get("worlds_dir", "simulation/worlds")).resolve()


def world_path(config: dict, name: str) -> Path:
    return worlds_dir(config) / f"{name}.sdf"


def validate_world(config: dict, name: str) -> Path:
    if name not in config["scenarios"]:
        fail(f"unknown scenario {name!r}. Run ./drone scenarios")
    path = world_path(config, name)
    if not path.is_file():
        fail(f"scenario world is missing: {path.relative_to(ROOT)}")
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        fail(f"invalid SDF XML in {path.name}: {exc}")
    world = root.find("world")
    if world is None:
        fail(f"{path.name} does not contain a <world>")
    if world.get("name") != name:
        fail(f"{path.name} world name must be {name!r}")
    return path


def px4_running() -> bool:
    try:
        state = json.loads(PX4_STATE.read_text(encoding="utf-8"))
        pid = int(state["pid"])
        os.kill(pid, 0)
        return True
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return False


def current_name(config: dict) -> str:
    try:
        selected = SELECTED.read_text(encoding="utf-8").strip()
    except OSError:
        selected = ""
    if selected in config["scenarios"]:
        return selected
    return config["default"]


def list_scenarios() -> None:
    config = load_config()
    current = current_name(config)
    default = config["default"]
    for name, meta in config["scenarios"].items():
        validate_world(config, name)
        flags = []
        if name == current:
            flags.append("selected")
        if name == default:
            flags.append("default")
        suffix = f" [{' / '.join(flags)}]" if flags else ""
        print(f"{name:<18} {meta.get('title', name)}{suffix}")
        description = meta.get("description", "")
        if description:
            print(f"  {description}")


def select(name: str) -> None:
    config = load_config()
    path = validate_world(config, name)
    if px4_running():
        fail("PX4/Gazebo is running. Run ./drone stop before changing scenario")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SELECTED.write_text(name + "\n", encoding="utf-8")
    print(f"[OK] selected scenario: {name}")
    print(f"[OK] world: {path.relative_to(ROOT)}")
    print("Next: ./drone start")


def reset() -> None:
    config = load_config()
    if px4_running():
        fail("PX4/Gazebo is running. Run ./drone stop before changing scenario")
    try:
        SELECTED.unlink()
    except FileNotFoundError:
        pass
    print(f"[OK] scenario reset to repository default: {config['default']}")


def print_current(name_only: bool = False) -> None:
    config = load_config()
    name = current_name(config)
    validate_world(config, name)
    if name_only:
        print(name)
        return
    meta = config["scenarios"][name]
    print(f"Scenario: {name} ({meta.get('title', name)})")
    print(f"World   : {world_path(config, name).relative_to(ROOT)}")


def is_known(name: str) -> None:
    config = load_config()
    if name not in config["scenarios"]:
        raise SystemExit(1)
    validate_world(config, name)


def main() -> None:
    args = sys.argv[1:]
    command = args[0] if args else "list"
    if command in {"list", "ls"}:
        list_scenarios()
    elif command in {"select", "set"}:
        if len(args) != 2:
            fail("Usage: ./drone scenario <name>")
        select(args[1])
    elif command == "reset":
        reset()
    elif command == "current":
        print_current("--name-only" in args[1:])
    elif command == "is-known":
        if len(args) != 2:
            raise SystemExit(1)
        is_known(args[1])
    else:
        fail(f"unknown scenario command: {command}")


if __name__ == "__main__":
    main()
