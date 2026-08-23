#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import bootstrap

ROOT = bootstrap.ROOT
RUNTIME = bootstrap.WORKSPACE / "runtime"
LOGS = RUNTIME / "logs"
SIMULATION = ROOT / "simulation"
WORLDS = SIMULATION / "worlds"
SCENARIOS = SIMULATION / "scenarios.json"

SERVER_STATE = RUNTIME / "gazebo-server.json"
GUI_STATE = RUNTIME / "gazebo-gui.json"
SERVER_LOG = LOGS / "gazebo-server.log"
GUI_LOG = LOGS / "gazebo-gui.log"

OWNER_ID = "drone-" + hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()[:12]
PARTITION = "drone_" + hashlib.sha256(str(ROOT.resolve()).encode()).hexdigest()[:12]


def say(message=""):
    print(message, flush=True)


def fail(message):
    raise SystemExit(f"[FAIL] {message}")


def ensure_dirs():
    bootstrap.ensure_dirs()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)


def read_state(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_state(path, data):
    ensure_dirs()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def clear_state(path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def process_start_ticks(pid):
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    end = text.rfind(")")
    fields = text[end + 2 :].split() if end >= 0 else []
    return fields[19] if len(fields) > 19 else None


def alive(state):
    if not state:
        return False
    try:
        pid = int(state["pid"])
        os.kill(pid, 0)
    except (KeyError, TypeError, ValueError, OSError):
        return False
    return process_start_ticks(pid) == state.get("start_ticks")


def identity(process, kind, **extra):
    return {
        "pid": process.pid,
        "pgid": process.pid,
        "start_ticks": process_start_ticks(process.pid),
        "kind": kind,
        "owner": OWNER_ID,
        "partition": PARTITION,
        **extra,
    }


def wait_for(predicate, seconds, interval=0.15):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def load_scenarios():
    try:
        return json.loads(SCENARIOS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read scenario configuration: {exc}")


def validate_scenario(name):
    config = load_scenarios()
    if name not in config.get("scenarios", {}):
        fail(f"unknown scenario {name!r}; run ./drone scenarios")
    world = WORLDS / f"{name}.sdf"
    if not world.is_file():
        fail(f"scenario world missing: {world.relative_to(ROOT)}")
    return world


def resolved_px4_dir():
    state = bootstrap.load_state() or {}
    resolved = state.get("resolved", {})
    px4_dir = Path(resolved.get("px4_dir", bootstrap.VENDOR / "px4-autopilot"))
    if not px4_dir.is_dir():
        fail(f"PX4 checkout missing: {px4_dir}")
    return px4_dir


def generated_gz_env(px4_dir):
    path = px4_dir / "build" / "px4_sitl_default" / "rootfs" / "gz_env.sh"
    if not path.is_file():
        fail(f"PX4 Gazebo environment is missing: {path}. Run ./dev setup first.")
    return path


def source_shell_environment(script, base_env):
    result = subprocess.run(
        ["bash", "-c", 'source "$1" >/dev/null 2>&1; env -0', "bash", str(script)],
        env=base_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        fail("could not load PX4 Gazebo environment")
    env = {}
    for item in result.stdout.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        env[key.decode(errors="replace")] = value.decode(errors="replace")
    return env


def gazebo_environment(px4_dir):
    base = os.environ.copy()
    base["GZ_PARTITION"] = PARTITION
    base["DRONE_RUNTIME_OWNER"] = OWNER_ID
    env = source_shell_environment(generated_gz_env(px4_dir), base)
    env["GZ_PARTITION"] = PARTITION
    env["DRONE_RUNTIME_OWNER"] = OWNER_ID

    existing = [p for p in env.get("GZ_SIM_RESOURCE_PATH", "").split(":") if p]
    world_path = str(WORLDS.resolve())
    if world_path not in existing:
        existing.insert(0, world_path)
    env["GZ_SIM_RESOURCE_PATH"] = ":".join(existing)
    return env


def validate_world_with_gazebo(world, env):
    result = subprocess.run(
        ["gz", "sdf", "-k", str(world)],
        env=env,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        details = result.stdout.strip() or "unknown SDF validation error"
        fail(f"Gazebo rejected {world.name}:\n{details}")


def world_ready(name, env):
    try:
        result = subprocess.run(
            ["gz", "service", "-i", "--service", f"/world/{name}/scene/info"],
            env=env,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=3,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False
    return result.returncode == 0 and "Service providers" in result.stdout


def process_environ(pid):
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return {}
    result = {}
    for item in raw.split(b"\0"):
        if b"=" in item:
            key, value = item.split(b"=", 1)
            result[key.decode(errors="replace")] = value.decode(errors="replace")
    return result


def process_cmdline(pid):
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        return ""


def process_cwd(pid):
    try:
        return Path(f"/proc/{pid}/cwd").resolve()
    except OSError:
        return None


def gazebo_like_process(pid):
    cmd = process_cmdline(pid)
    return "gz sim" in cmd or "gz-sim" in cmd or ("ruby" in cmd and "gz" in cmd and "sim" in cmd)


def terminate_pid_group(pid, label):
    try:
        pgid = os.getpgid(pid)
    except OSError:
        return True

    for sig, timeout in (
        (signal.SIGINT, 3.0),
        (signal.SIGTERM, 2.0),
        (signal.SIGKILL, 1.0),
    ):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return True
        except PermissionError:
            return False
        if wait_for(lambda: not Path(f"/proc/{pid}").exists(), timeout):
            say(f"[OK] stopped {label}")
            return True
    return not Path(f"/proc/{pid}").exists()


def terminate_state(path, label):
    state = read_state(path)
    if not state:
        return
    if not alive(state):
        clear_state(path)
        return
    if terminate_pid_group(int(state["pid"]), label):
        clear_state(path)
    else:
        say(f"[WARN] could not stop {label} pid={state['pid']}")


def cleanup_owned_orphans():
    cleaned = 0
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        pid = int(proc.name)
        env = process_environ(pid)
        if env.get("DRONE_RUNTIME_OWNER") != OWNER_ID:
            continue
        if not gazebo_like_process(pid):
            continue
        if terminate_pid_group(pid, f"orphaned managed Gazebo pid={pid}"):
            cleaned += 1
    return cleaned


def cleanup_legacy_px4_gazebo(px4_dir):
    """Recover Gazebo processes leaked by the previous PX4-launched runtime."""
    rootfs = (px4_dir / "build" / "px4_sitl_default" / "rootfs").resolve()
    cleaned = 0
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        pid = int(proc.name)
        if not gazebo_like_process(pid):
            continue
        cwd = process_cwd(pid)
        if cwd is None:
            continue
        try:
            cwd.relative_to(rootfs)
        except ValueError:
            continue
        if terminate_pid_group(pid, f"legacy PX4 Gazebo pid={pid}"):
            cleaned += 1
    return cleaned


def start_server(name, world, env):
    tracked = read_state(SERVER_STATE)
    if alive(tracked):
        if tracked.get("scenario") != name:
            fail(f"Gazebo server already runs scenario {tracked.get('scenario')!r}; run ./drone stop first")
        say(f"[OK] Gazebo server already running (pid {tracked['pid']})")
        return
    clear_state(SERVER_STATE)

    with SERVER_LOG.open("a", encoding="utf-8") as log:
        log.write(f"\n===== {time.strftime('%F %T')} scenario={name} =====\n")
        log.flush()
        process = subprocess.Popen(
            ["gz", "sim", "--force-version", "8", "-r", "-s", str(world)],
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    state = identity(process, "gazebo-server", scenario=name, world=str(world))
    write_state(SERVER_STATE, state)

    if not wait_for(lambda: alive(state) and world_ready(name, env), 20.0, 0.35):
        terminate_state(SERVER_STATE, "Gazebo server")
        tail = ""
        try:
            tail = "\n".join(SERVER_LOG.read_text(errors="replace").splitlines()[-30:])
        except OSError:
            pass
        fail(f"Gazebo server did not make world {name!r} ready.\n{tail}")
    say(f"[OK] Gazebo world ready: {name}")


def start_gui(env):
    tracked = read_state(GUI_STATE)
    if alive(tracked):
        say(f"[OK] Gazebo GUI already running (pid {tracked['pid']})")
        return
    clear_state(GUI_STATE)

    with GUI_LOG.open("a", encoding="utf-8") as log:
        log.write(f"\n===== {time.strftime('%F %T')} GUI =====\n")
        log.flush()
        process = subprocess.Popen(
            ["gz", "sim", "--force-version", "8", "-g"],
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    state = identity(process, "gazebo-gui")
    write_state(GUI_STATE, state)
    if not wait_for(lambda: alive(state), 2.0):
        clear_state(GUI_STATE)
        fail("Gazebo GUI exited immediately; inspect ./drone logs")
    say(f"[OK] Gazebo GUI started (pid {process.pid})")


def start(name):
    ensure_dirs()
    world = validate_scenario(name)
    px4_dir = resolved_px4_dir()
    cleanup_owned_orphans()
    cleanup_legacy_px4_gazebo(px4_dir)
    env = gazebo_environment(px4_dir)
    validate_world_with_gazebo(world, env)
    start_server(name, world, env)
    start_gui(env)


def stop():
    ensure_dirs()
    px4_dir = resolved_px4_dir()
    terminate_state(GUI_STATE, "Gazebo GUI")
    terminate_state(SERVER_STATE, "Gazebo server")
    cleanup_owned_orphans()
    cleanup_legacy_px4_gazebo(px4_dir)


def status():
    server = read_state(SERVER_STATE)
    gui = read_state(GUI_STATE)
    say(f"Gazebo server: {'RUNNING' if alive(server) else 'STOPPED'}")
    if alive(server):
        say(f"Scenario     : {server.get('scenario', '?')}")
        say(f"Server pid   : {server.get('pid')}")
    say(f"Gazebo GUI   : {'RUNNING' if alive(gui) else 'STOPPED'}")
    if alive(gui):
        say(f"GUI pid      : {gui.get('pid')}")
    say(f"GZ partition : {PARTITION}")


def logs():
    for path in (SERVER_LOG, GUI_LOG):
        say(f"\n===== {path.relative_to(ROOT)} =====")
        if not path.exists():
            say("(no log yet)")
            continue
        say("\n".join(path.read_text(errors="replace").splitlines()[-80:]))


def main():
    args = sys.argv[1:]
    command = args[0] if args else "status"
    if command == "start":
        if len(args) != 2:
            fail("Usage: gazebo_runtime.py start <scenario>")
        start(args[1])
    elif command in {"stop", "cleanup"}:
        stop()
    elif command == "status":
        status()
    elif command == "logs":
        logs()
    elif command == "partition":
        print(PARTITION)
    elif command == "owner":
        print(OWNER_ID)
    else:
        fail(f"unknown command: {command}")


if __name__ == "__main__":
    main()
