#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys

import bootstrap


def fail(message):
    raise SystemExit(f"[FAIL] {message}")


def manifest():
    return bootstrap.load_manifest()


def env_ready():
    m = manifest()
    info = bootstrap.detect_platform()
    if not bootstrap.verify(m, info, strict=False):
        print("[INFO] ROS/PX4 environment is not ready; repairing automatically", flush=True)
        bootstrap.setup(m)
    return bootstrap.ros_environment(m, include_workspace=True)


def normalize_node(name):
    return name if name.startswith("/") else "/" + name


def run(args, *, env, check=True):
    print("+ " + " ".join(args), flush=True)
    return subprocess.run(args, env=env, check=check)


def topics(env):
    run(["ros2", "topic", "list", "-t"], env=env)


def listen(topic, env, once=False):
    cmd = ["ros2", "topic", "echo", topic]
    if once:
        cmd += ["--once"]
    run(cmd, env=env)


def rate(topic, env):
    run(["ros2", "topic", "hz", topic], env=env)


def topic_info(topic, env):
    run(["ros2", "topic", "info", "-v", topic], env=env)


def nodes(env):
    run(["ros2", "node", "list"], env=env)


def node_info(node, env):
    run(["ros2", "node", "info", normalize_node(node)], env=env)


def run_node(node, env, extra):
    run(["ros2", "run", "drone", node, *extra], env=env)


def services(env):
    run(["ros2", "service", "list", "-t"], env=env)


def params(node, env):
    run(["ros2", "param", "list", normalize_node(node)], env=env)


def get_param(node, param, env):
    run(["ros2", "param", "get", normalize_node(node), param], env=env)


def set_param(node, param, value, env):
    run(["ros2", "param", "set", normalize_node(node), param, value], env=env)


def doctor(env):
    run(["ros2", "doctor", "--report"], env=env, check=False)


def help_text():
    print('''Usage:
  ./ros topics                    list topics + message types
  ./ros listen TOPIC              continuously echo a topic
  ./ros once TOPIC                print one message
  ./ros rate TOPIC                show publish frequency
  ./ros info TOPIC                publishers/subscribers/QoS
  ./ros nodes                     list nodes
  ./ros node NAME                 inspect node
  ./ros run NODE [args...]        run an already-built node
  ./ros services                  list services
  ./ros params NODE               list parameters
  ./ros get NODE PARAM            read parameter
  ./ros set NODE PARAM VALUE      write parameter
  ./ros send TOPIC TYPE DATA      publish one message
  ./ros call SERVICE TYPE DATA    call a service
  ./ros doctor                    ROS report

Aliases: t=topics, l=listen, o=once, hz=rate, n=nodes, r=run, s=services
''')


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "help"
    if cmd in {"help", "-h", "--help"}:
        help_text(); return
    env = env_ready()
    rest = args[1:]

    if cmd in {"topics", "t"}:
        topics(env)
    elif cmd in {"listen", "l"}:
        if len(rest) != 1: fail("Usage: ./ros listen TOPIC")
        listen(rest[0], env)
    elif cmd in {"once", "o"}:
        if len(rest) != 1: fail("Usage: ./ros once TOPIC")
        listen(rest[0], env, once=True)
    elif cmd in {"rate", "hz"}:
        if len(rest) != 1: fail("Usage: ./ros rate TOPIC")
        rate(rest[0], env)
    elif cmd == "info":
        if len(rest) != 1: fail("Usage: ./ros info TOPIC")
        topic_info(rest[0], env)
    elif cmd in {"nodes", "n"}:
        nodes(env)
    elif cmd == "node":
        if len(rest) != 1: fail("Usage: ./ros node NAME")
        node_info(rest[0], env)
    elif cmd in {"run", "r"}:
        if not rest: fail("Usage: ./ros run NODE [args...]")
        run_node(rest[0], env, rest[1:])
    elif cmd in {"services", "s"}:
        services(env)
    elif cmd == "params":
        if len(rest) != 1: fail("Usage: ./ros params NODE")
        params(rest[0], env)
    elif cmd == "get":
        if len(rest) != 2: fail("Usage: ./ros get NODE PARAM")
        get_param(rest[0], rest[1], env)
    elif cmd == "set":
        if len(rest) != 3: fail("Usage: ./ros set NODE PARAM VALUE")
        set_param(rest[0], rest[1], rest[2], env)
    elif cmd == "send":
        if len(rest) != 3: fail("Usage: ./ros send TOPIC TYPE DATA")
        run(["ros2", "topic", "pub", "--once", rest[0], rest[1], rest[2]], env=env)
    elif cmd == "call":
        if len(rest) != 3: fail("Usage: ./ros call SERVICE TYPE DATA")
        run(["ros2", "service", "call", rest[0], rest[1], rest[2]], env=env)
    elif cmd == "doctor":
        doctor(env)
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
