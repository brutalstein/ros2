#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import bootstrap

ROOT = bootstrap.ROOT
APP = ROOT / "app"
PACKAGE_XML = APP / "package.xml"
CODE_SUFFIXES = {".cpp", ".cc", ".cxx", ".hpp", ".h"}
NODE_RE = re.compile(r"(?m)^[ \t]*int\s+main\s*\(")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def say(message=""):
    print(message, flush=True)


def fail(message):
    raise SystemExit(f"[FAIL] {message}")


def manifest():
    return bootstrap.load_manifest()


def ensure_ready():
    m = manifest()
    info = bootstrap.detect_platform()
    if not bootstrap.verify(m, info, strict=False):
        say("[INFO] environment drift/missing dependency detected; repairing automatically")
        bootstrap.setup(m)
    return m, info


def read(path):
    return path.read_text(encoding="utf-8", errors="ignore")


def code_files():
    if not APP.exists():
        return []
    return sorted(p for p in APP.rglob("*") if p.is_file() and p.suffix in CODE_SUFFIXES)


def cpp_files():
    return [p for p in code_files() if p.suffix in {".cpp", ".cc", ".cxx"}]


def node_files():
    return [p for p in cpp_files() if NODE_RE.search(read(p))]


def node_map():
    nodes = {}
    duplicates = {}
    for path in node_files():
        name = path.stem
        if name in nodes:
            duplicates.setdefault(name, [nodes[name]]).append(path)
        else:
            nodes[name] = path
    if duplicates:
        lines = ["Duplicate node executable names found:"]
        for name, paths in sorted(duplicates.items()):
            lines.append(f"  {name}")
            lines.extend(f"    - {p.relative_to(ROOT)}" for p in paths)
        lines.append("Node filenames must be unique across app/.")
        fail("\n".join(lines))
    return nodes


def validate_project():
    errors = []
    if not APP.is_dir():
        errors.append("app/ directory is missing")
    if not PACKAGE_XML.is_file():
        errors.append("app/package.xml is missing")
    if not (APP / "CMakeLists.txt").is_file():
        errors.append("app/CMakeLists.txt is missing")
    if PACKAGE_XML.exists():
        try:
            ET.parse(PACKAGE_XML)
        except ET.ParseError as exc:
            errors.append(f"invalid package.xml: {exc}")
    try:
        node_map()
    except SystemExit as exc:
        errors.append(str(exc).removeprefix("[FAIL] "))
    if errors:
        fail("\n".join(errors))


def validate_rel_name(value, suffix):
    raw = value.strip().replace("\\", "/")
    if raw.endswith(suffix):
        raw = raw[: -len(suffix)]
    parts = [part for part in raw.split("/") if part]
    if not parts:
        fail("name cannot be empty")
    for part in parts:
        if not NAME_RE.fullmatch(part):
            fail("each path component must match [a-z][a-z0-9_]*")
    return Path(*parts)


def package_has_dep(dep):
    if not PACKAGE_XML.exists():
        return False
    return re.search(
        rf"<(?:depend|build_depend|exec_depend|buildtool_depend)>\s*{re.escape(dep)}\s*</",
        read(PACKAGE_XML),
    ) is not None


def add_dep(dep, quiet=False):
    if not NAME_RE.fullmatch(dep):
        fail("ROS package name must match [a-z][a-z0-9_]*")
    if package_has_dep(dep):
        if not quiet:
            say(f"[OK] dependency already present: {dep}")
        return False
    text = read(PACKAGE_XML)
    marker = "  <export>"
    if marker not in text:
        fail("package.xml has no <export> block")
    text = text.replace(marker, f"  <depend>{dep}</depend>\n\n{marker}", 1)
    PACKAGE_XML.write_text(text, encoding="utf-8")
    if not quiet:
        say(f"[OK] added dependency: {dep}")
    return True


def ros_package_exists(name, env):
    result = subprocess.run(
        ["ros2", "pkg", "prefix", name],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def sync_deps(env):
    include_re = re.compile(r'^\s*#\s*include\s*[<"]([A-Za-z][A-Za-z0-9_]*)/', re.MULTILINE)
    prefixes = set()
    for path in code_files():
        prefixes.update(include_re.findall(read(path)))
    added = []
    for prefix in sorted(prefixes):
        if package_has_dep(prefix):
            continue
        if ros_package_exists(prefix, env) and add_dep(prefix, quiet=True):
            added.append(prefix)
    if added:
        say("[OK] auto-added ROS dependencies: " + ", ".join(added))


def install_ros_deps(env):
    bootstrap.ensure_rosdep(manifest())
    bootstrap.run([
        "rosdep", "install",
        "--from-paths", APP,
        "--ignore-src", "-r", "-y",
    ], env=env)


def refresh_compile_commands():
    source = bootstrap.BUILD / "drone" / "compile_commands.json"
    target = bootstrap.WORKSPACE / "compile_commands.json"
    if not source.exists():
        say("[WARN] compiler database was not generated")
        return
    if target.exists() or target.is_symlink():
        target.unlink()
    target.symlink_to(Path("build/drone/compile_commands.json"))
    say("[OK] VS Code compiler database refreshed")


def build():
    m, info = ensure_ready()
    validate_project()
    env = bootstrap.ros_environment(m, include_workspace=True)
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = str(info["build_jobs"])
    sync_deps(env)
    install_ros_deps(env)
    bootstrap.run([
        "colcon", "--log-base", bootstrap.LOG, "build",
        "--base-paths", APP,
        "--build-base", bootstrap.BUILD,
        "--install-base", bootstrap.INSTALL,
        "--packages-select", "drone",
        "--symlink-install",
        "--event-handlers", "console_direct+",
        "--cmake-args", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
    ], env=env)
    refresh_compile_commands()
    say("[OK] build complete")


def clean():
    import shutil
    for path in (bootstrap.BUILD / "drone", bootstrap.INSTALL / "drone"):
        if path.exists():
            shutil.rmtree(path)
            say(f"[OK] removed {path.relative_to(ROOT)}")
    cc = bootstrap.WORKSPACE / "compile_commands.json"
    if cc.exists() or cc.is_symlink():
        cc.unlink()
    say("[OK] application clean complete; toolchain/vendor caches preserved")


def create_node(value):
    rel = validate_rel_name(value, ".cpp")
    path = APP / rel.with_suffix(".cpp")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        fail(f"already exists: {path.relative_to(ROOT)}")
    node = rel.name
    cls = "".join(part.capitalize() for part in node.split("_")) + "Node"
    path.write_text(
        f'''#include <memory>\n\n#include "rclcpp/rclcpp.hpp"\n\nclass {cls} final : public rclcpp::Node\n{{\npublic:\n    {cls}()\n        : rclcpp::Node("{node}")\n    {{\n        RCLCPP_INFO(get_logger(), "{node} started");\n    }}\n}};\n\nint main(int argc, char * argv[])\n{{\n    rclcpp::init(argc, argv);\n    rclcpp::spin(std::make_shared<{cls}>());\n    rclcpp::shutdown();\n    return 0;\n}}\n''',
        encoding="utf-8",
    )
    say(f"[OK] created {path.relative_to(ROOT)}")
    say(f"Run: ./dev r {node}")


def create_header(value):
    rel = validate_rel_name(value, ".hpp")
    path = APP / rel.with_suffix(".hpp")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        fail(f"already exists: {path.relative_to(ROOT)}")
    path.write_text("#pragma once\n", encoding="utf-8")
    say(f"[OK] created {path.relative_to(ROOT)}")


def resolve_node(name):
    nodes = node_map()
    if "/" in name or name.endswith(".cpp"):
        rel = validate_rel_name(name, ".cpp")
        path = APP / rel.with_suffix(".cpp")
        if not path.exists() or path not in node_files():
            fail(f"not a node source: {path.relative_to(ROOT)}")
        return path.stem
    if name not in nodes:
        fail(f"unknown node '{name}'. Available: {', '.join(sorted(nodes)) or '(none)'}")
    return name


def run_node(name, extra):
    target = resolve_node(name)
    build()
    m = manifest()
    env = bootstrap.ros_environment(m, include_workspace=True)
    bootstrap.run(["ros2", "run", "drone", target, *extra], env=env)


def list_nodes():
    nodes = node_map()
    for name, path in sorted(nodes.items()):
        say(f"{name:<22} {path.relative_to(ROOT)}")
    if not nodes:
        say("No nodes yet.")


def fmt():
    ensure_ready()
    bootstrap.apt_install_missing(["clang-format"])
    files = code_files()
    if files:
        bootstrap.run(["clang-format", "-i", *files])
    say(f"[OK] formatted {len(files)} files")


def check():
    validate_project()
    for script in sorted((ROOT / "tools").glob("*.py")):
        result = subprocess.run([sys.executable, "-m", "py_compile", str(script)], check=False)
        if result.returncode:
            fail(f"syntax check failed: {script.relative_to(ROOT)}")
    say(f"[OK] {len(node_map())} node(s) discovered")
    say("[OK] automation syntax/project checks passed")


def shell():
    m, _ = ensure_ready()
    ros_setup = Path(f"/opt/ros/{m['stack']['ros']['distro']}/setup.bash")
    ws_setup = bootstrap.INSTALL / "setup.bash"
    sources = f"source {ros_setup}"
    if ws_setup.exists():
        sources += f" && source {ws_setup}"
    os.execvp("bash", ["bash", "-lc", f"{sources} && exec bash"])


def help_text():
    say('''Usage:
  ./dev setup                 detect machine + install/repair pinned toolchain
  ./dev doctor                show OS/WSL/hardware detection
  ./dev verify                verify exact compatibility contract
  ./dev b | build             incremental application build
  ./dev rb | rebuild          application clean + build
  ./dev r NODE [args...]      build + run a node
  ./dev n PATH                create node (folders are optional)
  ./dev h PATH                create header
  ./dev ls | list             list discovered nodes
  ./dev d PKG                 add ROS dependency + build
  ./dev fmt                   install clang-format if needed + format code
  ./dev check                 project + Python automation checks
  ./dev clean                 remove only application build artifacts
  ./dev shell                 open ROS/workspace-ready shell

The pinned compatibility contract is toolchain.json.
External sources/dependencies live under .workspace/ and are never committed.
''')


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "help"
    rest = args[1:]
    m = manifest()

    if cmd in {"help", "-h", "--help"}:
        help_text()
    elif cmd in {"setup", "init"}:
        bootstrap.setup(m)
    elif cmd == "doctor":
        bootstrap.doctor(m)
    elif cmd == "verify":
        bootstrap.verify(m)
    elif cmd in {"b", "build"}:
        build()
    elif cmd in {"rb", "rebuild"}:
        clean(); build()
    elif cmd in {"r", "run"}:
        if not rest: fail("Usage: ./dev r NODE [args...]")
        run_node(rest[0], rest[1:])
    elif cmd in {"n", "node"}:
        if len(rest) != 1: fail("Usage: ./dev n PATH")
        create_node(rest[0])
    elif cmd in {"h", "header"}:
        if len(rest) != 1: fail("Usage: ./dev h PATH")
        create_header(rest[0])
    elif cmd in {"ls", "list"}:
        list_nodes()
    elif cmd in {"d", "dep"}:
        if len(rest) != 1: fail("Usage: ./dev d PACKAGE")
        add_dep(rest[0]); build()
    elif cmd == "fmt":
        fmt()
    elif cmd == "check":
        check()
    elif cmd == "clean":
        clean()
    elif cmd == "shell":
        shell()
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
