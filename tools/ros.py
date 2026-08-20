#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "drone"


def say(message=""):
    print(message)


def die(message, code=1):
    raise SystemExit(f"[FAIL] {message}")


def run(args, *, check=True):
    try:
        return subprocess.run(args, check=check)
    except FileNotFoundError:
        die(f"command not found: {args[0]}")
    except subprocess.CalledProcessError as exc:
        die(f"command failed with exit code {exc.returncode}")


def capture(args):
    try:
        result = subprocess.run(
            args,
            check=True,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result.stdout.strip()
    except FileNotFoundError:
        die(f"command not found: {args[0]}")
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.strip() or exc.stdout.strip() or "unknown ROS error"
        die(detail)


def clean_name(value, kind):
    value = value.strip()
    if not value:
        die(f"{kind} name cannot be empty")
    if any(ch.isspace() for ch in value):
        die(f"{kind} name cannot contain spaces: {value}")
    if not value.startswith("/"):
        value = "/" + value
    return value


def topics():
    output = capture(["ros2", "topic", "list"])
    return [line.strip() for line in output.splitlines() if line.strip()]


def nodes():
    output = capture(["ros2", "node", "list"])
    return [line.strip() for line in output.splitlines() if line.strip()]


def services():
    output = capture(["ros2", "service", "list"])
    return [line.strip() for line in output.splitlines() if line.strip()]


def require_topic(name):
    name = clean_name(name, "topic")
    available = topics()
    if name not in available:
        preview = "\n".join(f"  {item}" for item in available[:20]) or "  (none)"
        die(f"topic not found: {name}\nAvailable topics:\n{preview}")
    return name


def require_node(name):
    name = clean_name(name, "node")
    available = nodes()
    if name not in available:
        preview = "\n".join(f"  {item}" for item in available[:20]) or "  (none)"
        die(f"node not found: {name}\nAvailable nodes:\n{preview}")
    return name


def require_service(name):
    name = clean_name(name, "service")
    available = services()
    if name not in available:
        preview = "\n".join(f"  {item}" for item in available[:20]) or "  (none)"
        die(f"service not found: {name}\nAvailable services:\n{preview}")
    return name


def require_workspace():
    if not (ROOT / "install" / "setup.bash").exists():
        die("workspace is not built yet. Run: ./dev b")


def topic_list():
    output = capture(["ros2", "topic", "list", "-t"])
    say(output or "(no topics)")


def topic_listen(name, once=False):
    name = require_topic(name)
    args = ["ros2", "topic", "echo"]
    if once:
        args.append("--once")
    args.append(name)
    run(args)


def topic_rate(name):
    run(["ros2", "topic", "hz", require_topic(name)])


def topic_info(name):
    run(["ros2", "topic", "info", "-v", require_topic(name)])


def topic_send(name, msg_type, data):
    name = clean_name(name, "topic")
    if not msg_type.strip():
        die("message type cannot be empty")
    if not data.strip():
        die("message data cannot be empty")
    run(["ros2", "topic", "pub", "--once", name, msg_type, data])


def node_list():
    items = nodes()
    say("\n".join(items) if items else "(no nodes)")


def node_info(name):
    run(["ros2", "node", "info", require_node(name)])


def run_node(name):
    require_workspace()
    name = name.strip()
    if not name or "/" in name or any(ch.isspace() for ch in name):
        die("node executable must be a simple name, e.g. core")
    executables = capture(["ros2", "pkg", "executables", PACKAGE]).splitlines()
    names = {
        line.split(maxsplit=1)[1]
        for line in executables
        if len(line.split(maxsplit=1)) == 2
    }
    if name not in names:
        preview = "\n".join(f"  {item}" for item in sorted(names)) or "  (none)"
        die(
            f"executable not found: {name}\nBuilt executables:\n{preview}\n"
            "Run ./dev b after adding a node."
        )
    run(["ros2", "run", PACKAGE, name])


def service_list():
    output = capture(["ros2", "service", "list", "-t"])
    say(output or "(no services)")


def service_call(name, srv_type, data):
    name = require_service(name)
    if not srv_type.strip():
        die("service type cannot be empty")
    if not data.strip():
        die("service data cannot be empty")
    run(["ros2", "service", "call", name, srv_type, data])


def param_list(node):
    run(["ros2", "param", "list", require_node(node)])


def param_get(node, param):
    node = require_node(node)
    if not param.strip():
        die("parameter name cannot be empty")
    run(["ros2", "param", "get", node, param])


def param_set(node, param, value):
    node = require_node(node)
    if not param.strip():
        die("parameter name cannot be empty")
    if not value.strip():
        die("parameter value cannot be empty")
    run(["ros2", "param", "set", node, param, value])


def doctor():
    checks = [
        ("ROS_DISTRO", os.environ.get("ROS_DISTRO", "(unset)")),
        ("ROS_DOMAIN_ID", os.environ.get("ROS_DOMAIN_ID", "0")),
        ("workspace", "built" if (ROOT / "install" / "setup.bash").exists() else "not built"),
    ]
    for key, value in checks:
        say(f"[OK] {key}={value}")

    say(
        f"[OK] ROS graph reachable: {len(nodes())} node(s), "
        f"{len(topics())} topic(s), {len(services())} service(s)"
    )


def help_text():
    say(
        """ROS console

Topics
  ./ros topics
  ./ros listen TOPIC
  ./ros once TOPIC
  ./ros rate TOPIC
  ./ros info TOPIC
  ./ros send TOPIC TYPE DATA

Nodes
  ./ros nodes
  ./ros node NAME
  ./ros run NAME

Services
  ./ros services
  ./ros call SERVICE TYPE DATA

Parameters
  ./ros params NODE
  ./ros get NODE PARAM
  ./ros set NODE PARAM VALUE

System
  ./ros doctor
  ./ros help

Examples
  ./ros listen /drone/status
  ./ros once /drone/status
  ./ros run core
  ./ros send /demo std_msgs/msg/String '{data: hello}'
"""
    )


def need(args, count, usage):
    if len(args) < count:
        die(f"usage: {usage}")


def main():
    args = sys.argv[1:]
    command = args[0] if args else "help"
    rest = args[1:]

    aliases = {
        "t": "topics",
        "l": "listen",
        "o": "once",
        "hz": "rate",
        "n": "nodes",
        "r": "run",
        "s": "services",
        "h": "help",
    }
    command = aliases.get(command, command)

    if command == "topics":
        topic_list()
    elif command == "listen":
        need(rest, 1, "./ros listen TOPIC")
        topic_listen(rest[0])
    elif command == "once":
        need(rest, 1, "./ros once TOPIC")
        topic_listen(rest[0], once=True)
    elif command == "rate":
        need(rest, 1, "./ros rate TOPIC")
        topic_rate(rest[0])
    elif command == "info":
        need(rest, 1, "./ros info TOPIC")
        topic_info(rest[0])
    elif command == "send":
        need(rest, 3, "./ros send TOPIC TYPE DATA")
        topic_send(rest[0], rest[1], " ".join(rest[2:]))
    elif command == "nodes":
        node_list()
    elif command == "node":
        need(rest, 1, "./ros node NAME")
        node_info(rest[0])
    elif command == "run":
        need(rest, 1, "./ros run NAME")
        run_node(rest[0])
    elif command == "services":
        service_list()
    elif command == "call":
        need(rest, 3, "./ros call SERVICE TYPE DATA")
        service_call(rest[0], rest[1], " ".join(rest[2:]))
    elif command == "params":
        need(rest, 1, "./ros params NODE")
        param_list(rest[0])
    elif command == "get":
        need(rest, 2, "./ros get NODE PARAM")
        param_get(rest[0], rest[1])
    elif command == "set":
        need(rest, 3, "./ros set NODE PARAM VALUE")
        param_set(rest[0], rest[1], " ".join(rest[2:]))
    elif command == "doctor":
        doctor()
    elif command in {"help", "--help", "-h"}:
        help_text()
    else:
        die(f"unknown command: {command}\nRun ./ros help")


if __name__ == "__main__":
    main()
