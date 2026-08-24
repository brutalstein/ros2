#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import bootstrap
import qgroundcontrol

ROOT = bootstrap.ROOT
APP = ROOT / "app"
PACKAGE_XML = APP / "package.xml"
MAIN_CPP = APP / "main.cpp"
REGISTRY = APP / "runtime" / "node_registry.hpp"
ENTRY_EXECUTABLE = "drone_app"
CODE_SUFFIXES = {".cpp", ".cc", ".cxx", ".hpp", ".h"}
CPP_SUFFIXES = {".cpp", ".cc", ".cxx"}
MAIN_RE = re.compile(r"(?m)^[ \t]*int\s+main\s*\(")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
REGISTRY_ENTRY_RE = re.compile(
    r'\{\s*"([a-z][a-z0-9_]*)"\s*,\s*(make_[a-z][a-z0-9_]*_node)\s*\}'
)


def say(message: str = "") -> None:
    print(message, flush=True)


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] {message}")


def manifest() -> dict:
    return bootstrap.load_manifest()


def setup() -> None:
    m = manifest()
    bootstrap.setup(m)
    qgroundcontrol.setup()
    say("[OK] developer workspace ready")


def ensure_ready() -> tuple[dict, dict]:
    m = manifest()
    info = bootstrap.detect_platform()
    if not bootstrap.verify(m, info, strict=False):
        say("[INFO] toolchain drift detected; repairing automatically")
        bootstrap.setup(m)
    return m, info


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def code_files() -> list[Path]:
    if not APP.exists():
        return []
    return sorted(path for path in APP.rglob("*") if path.is_file() and path.suffix in CODE_SUFFIXES)


def cpp_files() -> list[Path]:
    return [path for path in code_files() if path.suffix in CPP_SUFFIXES]


def source_files() -> list[Path]:
    return [path for path in cpp_files() if path != MAIN_CPP]


def expected_header(path: Path) -> Path:
    return path.with_suffix(".hpp")


def expected_factory(path: Path) -> str:
    return f"make_{path.stem}_node"


def has_node_factory(path: Path) -> bool:
    header = expected_header(path)
    if not header.is_file():
        return False
    return re.search(rf"\b{re.escape(expected_factory(path))}\s*\(", read(header)) is not None


def source_kind(path: Path) -> str:
    return "node" if has_node_factory(path) else "helper"


def node_files() -> list[Path]:
    return [path for path in source_files() if source_kind(path) == "node"]


def helper_files() -> list[Path]:
    return [path for path in source_files() if source_kind(path) == "helper"]


def module_map() -> dict[str, Path]:
    modules: dict[str, Path] = {}
    for path in node_files():
        name = path.stem
        if name in modules:
            fail(
                f"duplicate node name {name!r}: "
                f"{modules[name].relative_to(ROOT)} and {path.relative_to(ROOT)}"
            )
        modules[name] = path
    return modules


def registry_nodes() -> dict[str, str]:
    if not REGISTRY.is_file():
        return {}
    result: dict[str, str] = {}
    for name, factory in REGISTRY_ENTRY_RE.findall(read(REGISTRY)):
        if name in result:
            fail(f"duplicate registry entry: {name}")
        result[name] = factory
    return result


def validate_module_contract(path: Path) -> list[str]:
    errors: list[str] = []
    header = expected_header(path)
    if not header.is_file():
        errors.append(f"{path.relative_to(ROOT)} needs matching {header.relative_to(ROOT)}")
        return errors
    factory = expected_factory(path)
    if re.search(rf"\b{re.escape(factory)}\s*\(", read(header)) is None:
        errors.append(f"{header.relative_to(ROOT)} must declare {factory}()")
    return errors


def validate_project() -> None:
    errors: list[str] = []
    for required in (APP, PACKAGE_XML, APP / "CMakeLists.txt", MAIN_CPP, REGISTRY):
        if not required.exists():
            errors.append(f"missing: {required.relative_to(ROOT)}")

    if PACKAGE_XML.exists():
        try:
            ET.parse(PACKAGE_XML)
        except ET.ParseError as exc:
            errors.append(f"invalid package.xml: {exc}")

    if MAIN_CPP.exists() and not MAIN_RE.search(read(MAIN_CPP)):
        errors.append("app/main.cpp must define the only int main(...)")

    for path in source_files():
        if MAIN_RE.search(read(path)):
            errors.append(f"{path.relative_to(ROOT)} defines main(); only app/main.cpp may do that")

    for path in node_files():
        errors.extend(validate_module_contract(path))

    try:
        discovered = module_map()
        registered = registry_nodes()
    except SystemExit as exc:
        errors.append(str(exc).removeprefix("[FAIL] "))
        discovered = {}
        registered = {}

    for name, path in discovered.items():
        expected = expected_factory(path)
        if name not in registered:
            errors.append(f"node {name!r} is not registered in app/runtime/node_registry.hpp")
        elif registered[name] != expected:
            errors.append(f"node {name!r} registry factory must be {expected}")
    for name in registered:
        if name not in discovered:
            errors.append(f"registry references missing node {name!r}")

    if errors:
        fail("\n".join(errors))


def validate_rel_name(value: str) -> Path:
    raw = value.strip().replace("\\", "/")
    for suffix in (".cpp", ".hpp"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
    parts = [part for part in raw.split("/") if part]
    if not parts:
        fail("node path cannot be empty")
    for part in parts:
        if not NAME_RE.fullmatch(part):
            fail("node path components must match [a-z][a-z0-9_]*")
    return Path(*parts)


def package_has_dep(dep: str) -> bool:
    if not PACKAGE_XML.exists():
        return False
    return re.search(
        rf"<(?:depend|build_depend|exec_depend|buildtool_depend)>\s*{re.escape(dep)}\s*</",
        read(PACKAGE_XML),
    ) is not None


def add_dep(dep: str) -> bool:
    if package_has_dep(dep):
        return False
    text = read(PACKAGE_XML)
    marker = "  <export>"
    if marker not in text:
        fail("package.xml has no <export> block")
    PACKAGE_XML.write_text(
        text.replace(marker, f"  <depend>{dep}</depend>\n\n{marker}", 1),
        encoding="utf-8",
    )
    return True


def ros_package_exists(name: str, env: dict) -> bool:
    result = subprocess.run(
        ["ros2", "pkg", "prefix", name],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def sync_deps(env: dict) -> None:
    include_re = re.compile(r'^\s*#\s*include\s*[<"]([A-Za-z][A-Za-z0-9_]*)/', re.MULTILINE)
    prefixes: set[str] = set()
    for path in code_files():
        prefixes.update(include_re.findall(read(path)))

    added = []
    for prefix in sorted(prefixes):
        if not package_has_dep(prefix) and ros_package_exists(prefix, env) and add_dep(prefix):
            added.append(prefix)
    if added:
        say("[OK] added ROS dependencies: " + ", ".join(added))


def install_ros_deps(env: dict) -> None:
    bootstrap.ensure_rosdep(manifest())
    bootstrap.run(
        ["rosdep", "install", "--from-paths", APP, "--ignore-src", "-r", "-y"],
        env=env,
    )


def refresh_compile_commands() -> None:
    source = bootstrap.BUILD / "drone" / "compile_commands.json"
    target = bootstrap.WORKSPACE / "compile_commands.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not source.exists():
        return
    if target.exists() or target.is_symlink():
        target.unlink()
    target.symlink_to(Path("build/drone/compile_commands.json"))


def build() -> None:
    m, info = ensure_ready()
    validate_project()
    env = bootstrap.ros_environment(m, include_workspace=True)
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = str(info["build_jobs"])
    sync_deps(env)
    install_ros_deps(env)

    command = [
        "colcon", "--log-base", bootstrap.LOG, "build",
        "--base-paths", APP,
        "--build-base", bootstrap.BUILD,
        "--install-base", bootstrap.INSTALL,
        "--packages-select", "drone",
        "--symlink-install",
        "--event-handlers", "console_direct+",
        "--cmake-args", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
    ]
    try:
        bootstrap.run(command, env=env)
    finally:
        refresh_compile_commands()
    say("[OK] build complete")


def register_node(rel: Path) -> None:
    text = read(REGISTRY)
    include_marker = "// DRONE_NODE_INCLUDES"
    entry_marker = "        // DRONE_NODE_ENTRIES"
    if include_marker not in text or entry_marker not in text:
        fail("node registry automation markers are missing")

    name = rel.name
    include = f'#include "{rel.with_suffix(".hpp").as_posix()}"'
    entry = f'        {{"{name}", make_{name}_node}},'

    if include not in text:
        text = text.replace(include_marker, include + "\n" + include_marker, 1)
    if name not in registry_nodes():
        text = text.replace(entry_marker, entry + "\n" + entry_marker, 1)
    REGISTRY.write_text(text, encoding="utf-8")


def create_node(value: str) -> None:
    rel = validate_rel_name(value)
    cpp_path = APP / rel.with_suffix(".cpp")
    hpp_path = APP / rel.with_suffix(".hpp")
    if cpp_path.exists() or hpp_path.exists():
        fail(f"node already exists: {rel}")
    if rel.name in module_map():
        fail(f"node name must be unique: {rel.name}")

    cpp_path.parent.mkdir(parents=True, exist_ok=True)
    node = rel.name
    class_name = "".join(part.capitalize() for part in node.split("_")) + "Node"
    header_rel = rel.with_suffix(".hpp").as_posix()

    hpp_path.write_text(
        '#pragma once\n\n#include <memory>\n\n#include "rclcpp/rclcpp.hpp"\n\n'
        f"std::shared_ptr<rclcpp::Node> make_{node}_node();\n",
        encoding="utf-8",
    )
    cpp_path.write_text(
        f'''#include <memory>\n\n#include "{header_rel}"\n\nclass {class_name} final : public rclcpp::Node\n{{\npublic:\n    {class_name}()\n        : rclcpp::Node("{node}")\n    {{\n        RCLCPP_INFO(get_logger(), "{node} ready");\n    }}\n}};\n\nstd::shared_ptr<rclcpp::Node> make_{node}_node()\n{{\n    return std::make_shared<{class_name}>();\n}}\n''',
        encoding="utf-8",
    )

    try:
        register_node(rel)
        validate_project()
    except BaseException:
        cpp_path.unlink(missing_ok=True)
        hpp_path.unlink(missing_ok=True)
        raise

    say(f"[OK] created and registered node: {node}")
    say(f"[INFO] source: {cpp_path.relative_to(ROOT)}")
    say(f"[INFO] test it with: ./dev run {node}")


def list_nodes() -> None:
    discovered = module_map()
    registered = registry_nodes()
    say("Nodes")
    for name, path in sorted(discovered.items()):
        state = "REGISTERED" if name in registered else "UNREGISTERED"
        say(f"  {name:<18} {state:<12} {path.relative_to(ROOT)}")


def run_node(name: str) -> None:
    validate_project()
    if name not in registry_nodes():
        fail(f"unknown node {name!r}; run ./dev nodes")
    build()
    m = manifest()
    env = bootstrap.ros_environment(m, include_workspace=True)
    env["DRONE_ONLY_NODE"] = name
    env.pop("DRONE_MISSION_AUTOSTART", None)
    say(f"[INFO] running only node: {name} | Ctrl+C to stop")
    bootstrap.run(["ros2", "run", "drone", ENTRY_EXECUTABLE], env=env)


def check() -> None:
    validate_project()
    for script in sorted((ROOT / "tools").glob("*.py")):
        result = subprocess.run([sys.executable, "-m", "py_compile", str(script)], check=False)
        if result.returncode:
            fail(f"Python syntax failed: {script.relative_to(ROOT)}")
    for script in (ROOT / "dev", ROOT / "mission", ROOT / "ros"):
        if subprocess.run(["bash", "-n", script], check=False).returncode:
            fail(f"shell syntax failed: {script.name}")
    say(f"[OK] project contract | {len(node_files())} nodes | {len(helper_files())} helpers")


def test_all() -> None:
    check()
    say("[INFO] running automation/unit tests")
    subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        cwd=ROOT,
        check=True,
    )
    build()
    say("[OK] developer test suite passed")


def clean() -> None:
    for path in (bootstrap.BUILD / "drone", bootstrap.INSTALL / "drone"):
        if path.exists():
            shutil.rmtree(path)
    compile_commands = bootstrap.WORKSPACE / "compile_commands.json"
    if compile_commands.exists() or compile_commands.is_symlink():
        compile_commands.unlink()
    say("[OK] application build artifacts cleaned")


def help_text() -> None:
    say(
        """Usage:
  ./dev setup          install/repair the pinned developer toolchain
  ./dev build          validate and build the complete C++ application
  ./dev test           run project checks + unit tests + full C++ build
  ./dev nodes          list discovered and registered ROS nodes
  ./dev new PATH       create and register a minimal ROS node
  ./dev run NAME       build and run exactly one registered node
  ./dev clean          remove application build artifacts only
"""
    )


def main() -> None:
    args = sys.argv[1:]
    command = args[0] if args else "help"
    rest = args[1:]

    if command == "setup":
        if rest:
            fail("Usage: ./dev setup")
        setup()
    elif command == "build":
        if rest:
            fail("Usage: ./dev build")
        build()
    elif command == "test":
        if rest:
            fail("Usage: ./dev test")
        test_all()
    elif command == "nodes":
        if rest:
            fail("Usage: ./dev nodes")
        list_nodes()
    elif command == "new":
        if len(rest) != 1:
            fail("Usage: ./dev new PATH")
        create_node(rest[0])
    elif command == "run":
        if len(rest) != 1:
            fail("Usage: ./dev run NAME")
        run_node(rest[0])
    elif command == "clean":
        if rest:
            fail("Usage: ./dev clean")
        clean()
    elif command in {"help", "-h", "--help"}:
        help_text()
    else:
        fail(f"unknown command: {command}")


if __name__ == "__main__":
    main()
