#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys

import bootstrap


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] {message}")


def env_ready() -> dict:
    manifest = bootstrap.load_manifest()
    info = bootstrap.detect_platform()
    if not bootstrap.verify(manifest, info, strict=False):
        print("[INFO] ROS environment drifted; repairing automatically", flush=True)
        bootstrap.setup(manifest)
    return bootstrap.ros_environment(manifest, include_workspace=True)


def run(args: list[str], env: dict) -> None:
    subprocess.run(args, env=env, check=True)


def normalize_node(name: str) -> str:
    return name if name.startswith("/") else "/" + name


def help_text() -> None:
    print(
        """Usage:
  ./ros topics          list topics and message types
  ./ros nodes           list active ROS nodes
  ./ros node NAME       inspect one active node
  ./ros echo TOPIC      continuously print a topic
  ./ros once TOPIC      print one message from a topic
  ./ros rate TOPIC      show topic publish frequency
  ./ros info TOPIC      show publishers, subscribers and QoS
"""
    )


def main() -> None:
    args = sys.argv[1:]
    command = args[0] if args else "help"
    rest = args[1:]

    if command in {"help", "-h", "--help"}:
        help_text()
        return

    env = env_ready()
    if command == "topics":
        if rest:
            fail("Usage: ./ros topics")
        run(["ros2", "topic", "list", "-t"], env)
    elif command == "nodes":
        if rest:
            fail("Usage: ./ros nodes")
        run(["ros2", "node", "list"], env)
    elif command == "node":
        if len(rest) != 1:
            fail("Usage: ./ros node NAME")
        run(["ros2", "node", "info", normalize_node(rest[0])], env)
    elif command == "echo":
        if len(rest) != 1:
            fail("Usage: ./ros echo TOPIC")
        run(["ros2", "topic", "echo", rest[0]], env)
    elif command == "once":
        if len(rest) != 1:
            fail("Usage: ./ros once TOPIC")
        run(["ros2", "topic", "echo", rest[0], "--once"], env)
    elif command == "rate":
        if len(rest) != 1:
            fail("Usage: ./ros rate TOPIC")
        run(["ros2", "topic", "hz", rest[0]], env)
    elif command == "info":
        if len(rest) != 1:
            fail("Usage: ./ros info TOPIC")
        run(["ros2", "topic", "info", "-v", rest[0]], env)
    else:
        fail(f"unknown command: {command}")


if __name__ == "__main__":
    main()
