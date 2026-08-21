#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

import dev as base

PX4_MSGS = base.ROOT / "vendor" / "px4_msgs"


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


def help_text():
    base.say('''Usage:
  ./dev setup                 first-time setup
  ./dev b | build             build everything
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
  ./dev clean                 remove build/install/log
  ./dev shell                 open a ROS-ready shell

Rules:
  - Work from the repository root: ~/ros2
  - C++ may live anywhere under app/
  - A .cpp file with int main(...) becomes a ROS executable automatically
  - Node filenames must be unique
  - Headers need no CMake edits
  - PX4 message interfaces are version-matched and managed under vendor/
''')


base.install_ros_deps = install_ros_deps
base.help_text = help_text

if __name__ == "__main__":
    base.main()
