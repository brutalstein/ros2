#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
PACKAGE_XML = APP / "package.xml"
ROS_DISTRO = os.environ.get("ROS_DISTRO", "jazzy")

CODE_SUFFIXES = {".cpp", ".cc", ".cxx", ".hpp", ".h"}
NODE_RE = re.compile(r"(?m)^[ \t]*int\s+main\s*\(")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def say(msg=""):
    print(msg)


def die(msg, code=1):
    raise SystemExit(f"[FAIL] {msg}")


def cmd_exists(name):
    return shutil.which(name) is not None


def run(cmd, *, cwd=ROOT, check=True, quiet=False):
    if not quiet:
        say("+ " + " ".join(map(str, cmd)))
    return subprocess.run(cmd, cwd=cwd, check=check)


def read(path):
    return path.read_text(encoding="utf-8", errors="ignore")


def code_files():
    if not APP.exists():
        return []
    return sorted(
        p for p in APP.rglob("*")
        if p.is_file() and p.suffix in CODE_SUFFIXES
    )


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
            for p in paths:
                lines.append(f"    - {p.relative_to(ROOT)}")
        lines.append("Rename one file so every node filename is unique.")
        die("\n".join(lines))

    return nodes


def validate_rel_name(value, suffix):
    raw = value.strip().replace("\\", "/")
    if raw.endswith(suffix):
        raw = raw[: -len(suffix)]

    parts = [p for p in raw.split("/") if p]
    if not parts:
        die("Name cannot be empty.")

    for part in parts:
        if not NAME_RE.fullmatch(part):
            die("Each path part must match: [a-z][a-z0-9_]*")

    return Path(*parts)


def package_has_dep(dep):
    text = read(PACKAGE_XML)
    return re.search(
        rf"<(?:depend|build_depend|exec_depend|buildtool_depend)>\s*{re.escape(dep)}\s*</",
        text,
    ) is not None


def add_dep(dep, *, quiet=False):
    if not NAME_RE.fullmatch(dep):
        die("ROS package name must match: [a-z][a-z0-9_]*")

    if package_has_dep(dep):
        if not quiet:
            say(f"[OK] dependency already present: {dep}")
        return False

    text = read(PACKAGE_XML)
    marker = "  <export>"
    if marker not in text:
        die("package.xml has no <export> block.")

    text = text.replace(marker, f"  <depend>{dep}</depend>\n\n{marker}", 1)
    PACKAGE_XML.write_text(text, encoding="utf-8")

    if not quiet:
        say(f"[OK] added dependency: {dep}")
    return True


def ros_package_exists(name):
    if not cmd_exists("ros2"):
        return False
    result = subprocess.run(
        ["ros2", "pkg", "prefix", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def sync_deps():
    include_re = re.compile(
        r'^\s*#\s*include\s*[<"]([A-Za-z][A-Za-z0-9_]*)/',
        re.MULTILINE,
    )
    prefixes = set()

    for path in code_files():
        prefixes.update(include_re.findall(read(path)))

    added = []
    for prefix in sorted(prefixes):
        if package_has_dep(prefix):
            continue
        if ros_package_exists(prefix):
            if add_dep(prefix, quiet=True):
                added.append(prefix)

    if added:
        say("[OK] auto-added ROS dependencies: " + ", ".join(added))

    return added


def check_project():
    problems = []

    if not APP.is_dir():
        problems.append("app/ directory is missing")
    if not PACKAGE_XML.is_file():
        problems.append("app/package.xml is missing")
    if not (APP / "CMakeLists.txt").is_file():
        problems.append("app/CMakeLists.txt is missing")

    if PACKAGE_XML.exists():
        try:
            ET.parse(PACKAGE_XML)
        except ET.ParseError as exc:
            problems.append(f"package.xml is invalid XML: {exc}")

    try:
        node_map()
    except SystemExit as exc:
        problems.append(str(exc).removeprefix("[FAIL] "))

    if problems:
        die("\n".join(problems))

    say("[OK] project structure")


def install_ros_deps():
    if not cmd_exists("rosdep"):
        return

    run([
        "rosdep", "install",
        "--from-paths", str(APP),
        "--ignore-src",
        "-r",
        "-y",
    ])


def refresh_compile_commands():
    source = ROOT / "build" / "drone" / "compile_commands.json"
    target = ROOT / "compile_commands.json"

    if not source.exists():
        return

    if target.exists() or target.is_symlink():
        target.unlink()

    target.symlink_to(Path("build/drone/compile_commands.json"))
    say("[OK] VS Code compile_commands refreshed")


def build():
    check_project()
    sync_deps()
    install_ros_deps()

    run([
        "colcon", "build",
        "--symlink-install",
        "--packages-select", "drone",
        "--event-handlers", "console_direct+",
        "--cmake-args",
        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
    ])

    refresh_compile_commands()
    say("[OK] build complete")


def clean():
    for name in ("build", "install", "log"):
        path = ROOT / name
        if path.exists():
            shutil.rmtree(path)
            say(f"[OK] removed {name}/")

    cc = ROOT / "compile_commands.json"
    if cc.exists() or cc.is_symlink():
        cc.unlink()

    say("[OK] clean")


def rebuild():
    clean()
    build()


def create_node(value):
    rel = validate_rel_name(value, ".cpp")
    path = APP / rel.with_suffix(".cpp")
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        die(f"already exists: {path.relative_to(ROOT)}")

    node = rel.name
    cls = "".join(x.capitalize() for x in node.split("_")) + "Node"

    path.write_text(
        f'''#include <memory>

#include "rclcpp/rclcpp.hpp"

class {cls} final : public rclcpp::Node
{{
public:
    {cls}()
        : rclcpp::Node("{node}")
    {{
        RCLCPP_INFO(get_logger(), "{node} started");
    }}
}};

int main(int argc, char * argv[])
{{
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<{cls}>());
    rclcpp::shutdown();
    return 0;
}}
''',
        encoding="utf-8",
    )

    say(f"[OK] created {path.relative_to(ROOT)}")
    say(f"Run later with: ./dev r {node}")


def create_header(value):
    rel = validate_rel_name(value, ".hpp")
    path = APP / rel.with_suffix(".hpp")
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        die(f"already exists: {path.relative_to(ROOT)}")

    path.write_text("#pragma once\n", encoding="utf-8")

    say(f"[OK] created {path.relative_to(ROOT)}")
    say(f'#include "{rel.as_posix()}.hpp"')


def resolve_node(name):
    nodes = node_map()

    if "/" in name or name.endswith(".cpp"):
        rel = validate_rel_name(name, ".cpp")
        path = APP / rel.with_suffix(".cpp")
        if not path.exists():
            die(f"node source not found: {path.relative_to(ROOT)}")
        if path not in node_files():
            die(f"{path.relative_to(ROOT)} has no int main(...)")
        return path.stem

    if name not in nodes:
        available = ", ".join(sorted(nodes)) or "(none)"
        die(f"unknown node '{name}'. Available: {available}")

    return name


def list_nodes():
    nodes = node_map()
    if not nodes:
        say("No nodes yet.")
        return

    for name, path in sorted(nodes.items()):
        say(f"{name:<20} {path.relative_to(ROOT)}")


def run_node(name, extra_args):
    target = resolve_node(name)
    build()

    setup = ROOT / "install" / "setup.bash"
    if not setup.exists():
        die("install/setup.bash missing after build")

    shell_cmd = [
        "bash", "-lc",
        'source "$1" && shift && exec "$@"',
        "dev-run",
        str(setup),
        "ros2", "run", "drone", target,
        *extra_args,
    ]
    run(shell_cmd)


def add_dependency(dep):
    changed = add_dep(dep)
    if changed:
        install_ros_deps()
    build()


def fmt():
    if not cmd_exists("clang-format"):
        die("clang-format is not installed. Install with: sudo apt install clang-format")

    files = code_files()
    if not files:
        say("No C/C++ files to format.")
        return

    run(["clang-format", "-i", *map(str, files)])
    say(f"[OK] formatted {len(files)} files")


def fast_check():
    check_project()

    result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(Path(__file__).resolve())]
    )
    if result.returncode != 0:
        die("tools/dev.py syntax check failed")

    if cmd_exists("cmake"):
        say("[OK] cmake available")
    else:
        die("cmake not found")

    say(f"[OK] {len(node_map())} node(s) discovered")
    say("[OK] automation self-check")


def doctor():
    proc_version = read(Path("/proc/version")).lower() if Path("/proc/version").exists() else ""
    os_release = read(Path("/etc/os-release")) if Path("/etc/os-release").exists() else ""

    checks = [
        ("WSL", "microsoft" in proc_version),
        ("Ubuntu 24.04", 'VERSION_ID="24.04"' in os_release),
        ("ROS 2", cmd_exists("ros2")),
        ("ROS Jazzy", ROS_DISTRO == "jazzy"),
        ("colcon", cmd_exists("colcon")),
        ("rosdep", cmd_exists("rosdep")),
        ("CMake", cmd_exists("cmake")),
        ("g++", cmd_exists("g++")),
        ("Gazebo", cmd_exists("gz")),
        ("VS Code", cmd_exists("code")),
        ("NVIDIA", cmd_exists("nvidia-smi")),
    ]

    say(f"ROS_DISTRO={ROS_DISTRO}")
    failed = 0
    for label, ok in checks:
        say(f"[{'OK' if ok else '--'}] {label}")
        failed += 0 if ok else 1

    try:
        check_project()
    except SystemExit as exc:
        say(str(exc))
        failed += 1

    if cmd_exists("gz"):
        subprocess.run(["gz", "sim", "--version"], check=False)
    if cmd_exists("nvidia-smi"):
        subprocess.run([
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader",
        ], check=False)

    if failed:
        say(f"[WARN] {failed} check(s) need attention")
    else:
        say("[OK] environment looks ready")


def apt_install(packages):
    run(["sudo", "apt-get", "update"])
    run(["sudo", "apt-get", "install", "-y", *packages])


def setup():
    needed = []
    if not cmd_exists("colcon"):
        needed.append("python3-colcon-common-extensions")
    if not cmd_exists("rosdep"):
        needed.append("python3-rosdep")
    if not cmd_exists("cmake"):
        needed.append("cmake")
    if not cmd_exists("g++"):
        needed.append("g++")

    if needed:
        apt_install(needed)

    if not ros_package_exists("ament_cmake_auto"):
        apt_install([f"ros-{ROS_DISTRO}-ament-cmake-auto"])

    rosdep_sources = Path("/etc/ros/rosdep/sources.list.d/20-default.list")
    if cmd_exists("rosdep"):
        if not rosdep_sources.exists():
            run(["sudo", "rosdep", "init"])
        run(["rosdep", "update"])

    if cmd_exists("code"):
        for ext in (
            "ms-vscode.cpptools",
            "ms-vscode.cmake-tools",
            "ms-iot.vscode-ros",
        ):
            run(["code", "--install-extension", ext, "--force"], check=False)

    doctor()
    build()
    say("[OK] setup complete")


def shell():
    if not (ROOT / "install" / "setup.bash").exists():
        build()
    os.execvp("bash", ["bash"])


def help_text():
    say('''Usage:
  ./dev setup                 first-time setup
  ./dev b | build             build everything
  ./dev rb | rebuild          clean + build
  ./dev r NODE [args...]      build + run a node
  ./dev n PATH                create node, e.g. sensors/imu
  ./dev h PATH                create header, e.g. constants/topics
  ./dev ls | list             list discovered nodes
  ./dev d PKG                 add ROS dependency
  ./dev check                 fast project/automation checks
  ./dev doctor                WSL/ROS/Gazebo/GPU environment checks
  ./dev fmt                   clang-format all C/C++ files
  ./dev clean                 remove build/install/log
  ./dev shell                 open a ROS-ready shell

Rules:
  - Work from the repository root: ~/ros2
  - C++ may live anywhere under app/
  - A .cpp file with int main(...) becomes a ROS executable automatically
  - Node filenames must be unique
  - Headers need no CMake edits
''')


def main():
    args = sys.argv[1:]
    command = args[0] if args else "help"
    rest = args[1:]

    aliases = {
        "b": "build",
        "rb": "rebuild",
        "r": "run",
        "n": "node",
        "h": "header",
        "d": "dep",
        "ls": "list",
        "c": "clean",
        "s": "setup",
    }
    command = aliases.get(command, command)

    try:
        if command == "setup":
            setup()
        elif command == "build":
            build()
        elif command == "rebuild":
            rebuild()
        elif command == "run":
            if not rest:
                die("Usage: ./dev r NODE [args...]")
            run_node(rest[0], rest[1:])
        elif command == "node":
            if len(rest) != 1:
                die("Usage: ./dev n PATH")
            create_node(rest[0])
        elif command == "header":
            if len(rest) != 1:
                die("Usage: ./dev h PATH")
            create_header(rest[0])
        elif command == "dep":
            if len(rest) != 1:
                die("Usage: ./dev d ROS_PACKAGE")
            add_dependency(rest[0])
        elif command == "list":
            list_nodes()
        elif command == "check":
            fast_check()
        elif command == "doctor":
            doctor()
        elif command == "fmt":
            fmt()
        elif command == "clean":
            clean()
        elif command == "shell":
            shell()
        else:
            help_text()
    except subprocess.CalledProcessError as exc:
        die(f"command failed with exit code {exc.returncode}")


if __name__ == "__main__":
    main()
