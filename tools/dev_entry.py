#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import dev as base
import workspace_layout as layout

PX4_MSGS = layout.VENDOR_DIR / "px4_msgs"
PX4_BOOTSTRAP = base.ROOT / "tools" / "px4_bootstrap.py"


def install_ros_deps():
    if not base.cmd_exists("rosdep"):
        return

    source_paths = [base.APP]
    if (PX4_MSGS / "package.xml").is_file():
        source_paths.append(PX4_MSGS)

    command = ["rosdep", "install", "--from-paths"]
    command.extend(str(path) for path in source_paths)
    command.extend(["--ignore-src", "-r", "-y"])
    base.run(command)


def refresh_compile_commands():
    source = layout.BUILD_DIR / "drone" / "compile_commands.json"
    target = layout.COMPILE_COMMANDS

    if not source.exists():
        base.say("[WARN] compile_commands.json was not generated")
        return

    layout.STATE_DIR.mkdir(parents=True, exist_ok=True)
    if target.exists() or target.is_symlink():
        target.unlink()

    target.symlink_to(Path("build/drone/compile_commands.json"))
    base.say("[OK] VS Code compile_commands refreshed")


def build():
    layout.ensure()
    base.check_project()
    base.sync_deps()
    install_ros_deps()

    base.run([
        "colcon",
        "--log-base", str(layout.LOG_DIR),
        "build",
        "--base-paths", str(base.APP),
        "--build-base", str(layout.BUILD_DIR),
        "--install-base", str(layout.INSTALL_DIR),
        "--symlink-install",
        "--packages-select", "drone",
        "--event-handlers", "console_direct+",
        "--cmake-args",
        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
    ])

    refresh_compile_commands()
    base.say("[OK] build complete")


def clean():
    layout.ensure()

    for path in (layout.BUILD_DIR, layout.INSTALL_DIR, layout.LOG_DIR):
        if path.exists():
            shutil.rmtree(path)
            base.say(f"[OK] removed {path.relative_to(base.ROOT)}/")

    if layout.COMPILE_COMMANDS.exists() or layout.COMPILE_COMMANDS.is_symlink():
        layout.COMPILE_COMMANDS.unlink()

    # External source and metadata are intentionally preserved.
    base.say("[OK] clean")


def run_node(name, extra_args):
    target = base.resolve_node(name)
    build()

    setup = layout.INSTALL_DIR / "setup.bash"
    if not setup.exists():
        base.die("workspace setup is missing after build")

    shell_cmd = [
        "bash", "-lc",
        'source "$1" && shift && exec "$@"',
        "dev-run",
        str(setup),
        "ros2", "run", "drone", target,
        *extra_args,
    ]
    base.run(shell_cmd)


def shell():
    layout.ensure()
    setup = layout.INSTALL_DIR / "setup.bash"
    if not setup.exists():
        build()

    os.execvp(
        "bash",
        ["bash", "-lc", f'source "{setup}" && exec bash'],
    )


def install_prerequisites():
    needed = []
    if not base.cmd_exists("colcon"):
        needed.append("python3-colcon-common-extensions")
    if not base.cmd_exists("rosdep"):
        needed.append("python3-rosdep")
    if not base.cmd_exists("cmake"):
        needed.append("cmake")
    if not base.cmd_exists("g++"):
        needed.append("g++")

    if needed:
        base.apt_install(needed)

    if not base.ros_package_exists("ament_cmake_auto"):
        base.apt_install([f"ros-{base.ROS_DISTRO}-ament-cmake-auto"])

    rosdep_sources = Path("/etc/ros/rosdep/sources.list.d/20-default.list")
    if base.cmd_exists("rosdep"):
        if not rosdep_sources.exists():
            base.run(["sudo", "rosdep", "init"])
        base.run(["rosdep", "update"])

    if base.cmd_exists("code"):
        for extension in (
            "ms-vscode.cpptools",
            "ms-vscode.cmake-tools",
            "ms-iot.vscode-ros",
        ):
            base.run(["code", "--install-extension", extension, "--force"], check=False)


def init_workspace():
    """Idempotent first-run setup for this repository."""
    layout.ensure()
    base.say("[INFO] initializing managed workspace")

    install_prerequisites()
    base.check_project()

    # Prepare PX4 message interfaces after the compiler/colcon prerequisites exist.
    base.run([sys.executable, str(PX4_BOOTSTRAP), "--auto"])

    # px4_msgs may have just been installed, so build the application in a fresh
    # shell that sources the newly generated workspace environment.
    setup = layout.INSTALL_DIR / "setup.bash"
    ros_setup = Path(f"/opt/ros/{base.ROS_DISTRO}/setup.bash")
    command = (
        f'source "{ros_setup}" && '
        + (f'source "{setup}" && ' if setup.exists() else "")
        + f'exec python3 "{Path(__file__).resolve()}" build'
    )
    base.run(["bash", "-lc", command])

    if not layout.COMPILE_COMMANDS.exists():
        base.die("workspace initialized but compile_commands.json is missing")

    layout.status()
    base.say("[OK] workspace initialized")
    base.say("[OK] VS Code C++/ROS/PX4 paths are ready")
    base.say("Next: write code, then run ./dev b")


def fast_check():
    layout.ensure()
    base.check_project()

    scripts = (
        Path(base.__file__).resolve(),
        Path(__file__).resolve(),
        Path(layout.__file__).resolve(),
        PX4_BOOTSTRAP,
        base.ROOT / "tools" / "ros.py",
        base.ROOT / "tools" / "drone.py",
    )
    for script in scripts:
        result = subprocess.run([sys.executable, "-m", "py_compile", str(script)])
        if result.returncode != 0:
            base.die(f"syntax check failed: {script.relative_to(base.ROOT)}")

    if not base.cmd_exists("cmake"):
        base.die("cmake not found")

    base.say("[OK] cmake available")
    base.say(f"[OK] {len(base.node_map())} node(s) discovered")
    layout.status()
    base.say("[OK] automation self-check")


def help_text():
    base.say('''Usage:
  ./dev init workspace        one-command workspace initialization
  ./dev b | build             incremental build + refresh IntelliSense
  ./dev rb | rebuild          clean + build
  ./dev r NODE [args...]      build + run a node
  ./dev n PATH                create node, e.g. sensors/imu
  ./dev h PATH                create header, e.g. constants/topics
  ./dev ls | list             list discovered nodes
  ./dev d PKG                 add ROS dependency
  ./dev px4                   prepare/check PX4 ROS interfaces
  ./dev check                 fast project/automation checks
  ./dev doctor                WSL/ROS/Gazebo/GPU environment checks
  ./dev fmt                   clang-format all C/C++ files
  ./dev clean                 remove generated build/install/log
  ./dev shell                 open a ROS-ready shell

Rules:
  - Work from the repository root: ~/ros2
  - C++ may live anywhere under app/
  - A .cpp file with int main(...) becomes a ROS executable automatically
  - Node filenames must be unique
  - Headers need no CMake edits
  - Generated state lives only under .workspace/
  - PX4 message interfaces are version-matched under .workspace/vendor/
''')


base.install_ros_deps = install_ros_deps
base.refresh_compile_commands = refresh_compile_commands
base.build = build
base.clean = clean
base.run_node = run_node
base.shell = shell
base.fast_check = fast_check
base.help_text = help_text


def main():
    args = sys.argv[1:]
    if args and args[0] == "init":
        if args[1:] != ["workspace"]:
            base.die("Usage: ./dev init workspace")
        init_workspace()
        return

    base.main()


if __name__ == "__main__":
    main()
