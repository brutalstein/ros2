#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "app"
SRC = PKG / "src"
INC = PKG / "include" / "drone"
PACKAGE_XML = PKG / "package.xml"
ROS_DISTRO = os.environ.get("ROS_DISTRO", "jazzy")


def run(cmd, *, cwd=ROOT, check=True):
    print("+", " ".join(map(str, cmd)))
    return subprocess.run(cmd, cwd=cwd, check=check)


def exists(cmd):
    return shutil.which(cmd) is not None


def ensure_dirs():
    SRC.mkdir(parents=True, exist_ok=True)
    INC.mkdir(parents=True, exist_ok=True)


def valid_name(name):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise SystemExit("Name must match: [a-z][a-z0-9_]*")


def class_name(name):
    return "".join(part.capitalize() for part in name.split("_")) + "Node"


def package_has_dep(dep):
    text = PACKAGE_XML.read_text()
    return re.search(
        rf"<(?:depend|build_depend|exec_depend|buildtool_depend)>\s*{re.escape(dep)}\s*</",
        text,
    ) is not None


def add_dep(dep, quiet=False):
    valid_name(dep)
    if package_has_dep(dep):
        return False

    text = PACKAGE_XML.read_text()
    marker = "  <export>"
    if marker not in text:
        raise SystemExit("package.xml has no <export> block.")

    text = text.replace(marker, f"  <depend>{dep}</depend>\n\n{marker}", 1)
    PACKAGE_XML.write_text(text)

    if not quiet:
        print(f"Added ROS dependency: {dep}")
    return True


def ros_package_exists(name):
    result = subprocess.run(
        ["ros2", "pkg", "prefix", name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def sync_deps():
    ensure_dirs()
    include_re = re.compile(r'^\s*#\s*include\s*[<"]([A-Za-z][A-Za-z0-9_]*)/', re.M)
    prefixes = set()

    for base in (SRC, INC):
        for path in base.rglob("*"):
            if path.suffix not in {".cpp", ".cc", ".cxx", ".hpp", ".h"}:
                continue
            prefixes.update(include_re.findall(path.read_text(errors="ignore")))

    prefixes.discard("drone")

    added = []
    for prefix in sorted(prefixes):
        if not package_has_dep(prefix) and ros_package_exists(prefix):
            if add_dep(prefix, quiet=True):
                added.append(prefix)

    if added:
        print("Auto-added dependencies:", ", ".join(added))


def install_ros_deps():
    if not exists("rosdep"):
        return
    run(
        [
            "rosdep",
            "install",
            "--from-paths",
            str(PKG),
            "--ignore-src",
            "-r",
            "-y",
        ]
    )


def link_compile_commands():
    target = ROOT / "build" / "drone" / "compile_commands.json"
    link = ROOT / "compile_commands.json"

    if not target.exists():
        return

    if link.exists() or link.is_symlink():
        link.unlink()

    link.symlink_to(Path("build/drone/compile_commands.json"))


def build():
    sync_deps()
    install_ros_deps()
    run(
        [
            "colcon",
            "build",
            "--symlink-install",
            "--packages-select",
            "drone",
            "--cmake-args",
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
        ]
    )
    link_compile_commands()
    print("\nBuild ready. VS Code compile_commands refreshed.")


def create_node(name):
    valid_name(name)
    ensure_dirs()
    path = SRC / f"{name}.cpp"

    if path.exists():
        raise SystemExit(f"Already exists: {path.relative_to(ROOT)}")

    cls = class_name(name)
    path.write_text(
        f'''#include <memory>

#include "rclcpp/rclcpp.hpp"

class {cls} final : public rclcpp::Node
{{
public:
    {cls}()
        : rclcpp::Node("{name}")
    {{
        RCLCPP_INFO(this->get_logger(), "{name} started");
    }}
}};

int main(int argc, char * argv[])
{{
    rclcpp::init(argc, argv);
    rclcpp::spin(std::make_shared<{cls}>());
    rclcpp::shutdown();
    return 0;
}}
'''
    )

    print(f"Created: {path.relative_to(ROOT)}")
    build()


def create_header(name):
    valid_name(name)
    ensure_dirs()
    path = INC / f"{name}.hpp"

    if path.exists():
        raise SystemExit(f"Already exists: {path.relative_to(ROOT)}")

    path.write_text(
        '''#pragma once

namespace drone
{

}  // namespace drone
'''
    )

    print(f"Created: {path.relative_to(ROOT)}")
    print(f'Use with: #include "drone/{name}.hpp"')
    print("No CMake edit is needed.")


def add_dependency(dep):
    add_dep(dep)
    install_ros_deps()
    build()


def run_node(name):
    valid_name(name)
    build()
    command = (
        f'source "/opt/ros/{ROS_DISTRO}/setup.bash" && '
        f'source "{ROOT}/install/setup.bash" && '
        f"ros2 run drone {name}"
    )
    subprocess.run(["bash", "-lc", command], cwd=ROOT, check=True)


def clean():
    for name in ("build", "install", "log"):
        path = ROOT / name
        if path.exists():
            shutil.rmtree(path)

    compile_commands = ROOT / "compile_commands.json"
    if compile_commands.exists() or compile_commands.is_symlink():
        compile_commands.unlink()

    print("Clean.")


def apt_install(packages):
    run(["sudo", "apt-get", "update"])
    run(["sudo", "apt-get", "install", "-y", *packages])


def setup():
    packages = []

    if not exists("colcon"):
        packages.append("python3-colcon-common-extensions")
    if not exists("rosdep"):
        packages.append("python3-rosdep")

    if packages:
        apt_install(packages)

    if not ros_package_exists("ament_cmake_auto"):
        apt_install([f"ros-{ROS_DISTRO}-ament-cmake-auto"])

    rosdep_list = Path("/etc/ros/rosdep/sources.list.d/20-default.list")
    if exists("rosdep"):
        if not rosdep_list.exists():
            run(["sudo", "rosdep", "init"])
        run(["rosdep", "update"])

    if exists("code"):
        for extension in (
            "ms-vscode.cpptools",
            "ms-vscode.cmake-tools",
            "ms-iot.vscode-ros",
        ):
            run(["code", "--install-extension", extension, "--force"], check=False)

    build()
    print("\nSetup complete. Open this folder with: code .")


def doctor():
    checks = [
        ("ROS 2", ros_package_exists("rclcpp")),
        ("ament_cmake_auto", ros_package_exists("ament_cmake_auto")),
        ("colcon", exists("colcon")),
        ("rosdep", exists("rosdep")),
        ("g++", exists("g++")),
        ("Gazebo", exists("gz")),
        ("VS Code", exists("code")),
        ("NVIDIA", exists("nvidia-smi")),
    ]

    print(f"ROS_DISTRO: {ROS_DISTRO}")
    for name, ok in checks:
        print(f"[{'OK' if ok else '--'}] {name}")

    if exists("gz"):
        subprocess.run(["gz", "sim", "--version"], check=False)
    if exists("nvidia-smi"):
        subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,driver_version",
                "--format=csv,noheader",
            ],
            check=False,
        )


def help_text():
    print(
        '''Usage:
  ./dev setup            one-time WSL/VS Code setup
  ./dev build | b        build and refresh IntelliSense
  ./dev node NAME | n    create a ROS 2 node and build it
  ./dev header NAME | h  create include/drone/NAME.hpp
  ./dev dep PACKAGE | d  add a ROS dependency
  ./dev run NAME | r     build and run a node
  ./dev doctor           check ROS/Gazebo/WSL tools
  ./dev clean            remove generated build files

You may also create app/src/*.cpp or app/include/drone/*.hpp by hand.
CMake discovers source nodes automatically; headers need no CMake edits.
'''
    )


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "help"
    arg = sys.argv[2] if len(sys.argv) > 2 else None

    aliases = {
        "b": "build",
        "n": "node",
        "h": "header",
        "d": "dep",
        "r": "run",
        "s": "setup",
        "c": "clean",
    }
    command = aliases.get(command, command)

    if command == "setup":
        setup()
    elif command == "build":
        build()
    elif command == "node":
        if not arg:
            raise SystemExit("Usage: ./dev node NAME")
        create_node(arg)
    elif command == "header":
        if not arg:
            raise SystemExit("Usage: ./dev header NAME")
        create_header(arg)
    elif command == "dep":
        if not arg:
            raise SystemExit("Usage: ./dev dep PACKAGE")
        add_dependency(arg)
    elif command == "run":
        if not arg:
            raise SystemExit("Usage: ./dev run NAME")
        run_node(arg)
    elif command == "doctor":
        doctor()
    elif command == "clean":
        clean()
    else:
        help_text()


if __name__ == "__main__":
    main()
