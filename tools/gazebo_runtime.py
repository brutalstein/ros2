#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
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


def say(message: str = "") -> None:
    print(message, flush=True)


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] {message}")


def ensure_dirs() -> None:
    bootstrap.ensure_dirs()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)


def read_state(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_state(path: Path, data: dict) -> None:
    ensure_dirs()
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def clear_state(path: Path) -> None:
    path.unlink(missing_ok=True)


def process_start_ticks(pid: int) -> str | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    end = text.rfind(")")
    fields = text[end + 2 :].split() if end >= 0 else []
    return fields[19] if len(fields) > 19 else None


def pid_identity_alive(state: dict | None) -> bool:
    if not state:
        return False
    try:
        pid = int(state["pid"])
        os.kill(pid, 0)
    except (KeyError, TypeError, ValueError, OSError):
        return False
    return process_start_ticks(pid) == state.get("start_ticks")


def pgid_alive(pgid: int | str | None) -> bool:
    try:
        os.killpg(int(pgid), 0)
        return True
    except (OSError, TypeError, ValueError):
        return False


def state_active(state: dict | None) -> bool:
    return bool(state and (pid_identity_alive(state) or pgid_alive(state.get("pgid"))))


def identity(process: subprocess.Popen, kind: str, **extra) -> dict:
    return {
        "pid": process.pid,
        "pgid": os.getpgid(process.pid),
        "start_ticks": process_start_ticks(process.pid),
        "kind": kind,
        "owner": OWNER_ID,
        "partition": PARTITION,
        **extra,
    }


def wait_for(predicate, seconds: float, interval: float = 0.15) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def load_scenarios() -> dict:
    try:
        return json.loads(SCENARIOS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read scenario configuration: {exc}")


def validate_scenario(name: str) -> Path:
    config = load_scenarios()
    if name not in config.get("scenarios", {}):
        fail(f"unknown scenario {name!r}; run ./mission scenario")
    world = WORLDS / f"{name}.sdf"
    if not world.is_file():
        fail(f"scenario world missing: {world.relative_to(ROOT)}")
    return world


def resolved_px4_dir() -> Path:
    state = bootstrap.load_state() or {}
    resolved = state.get("resolved", {})
    px4_dir = Path(resolved.get("px4_dir", bootstrap.VENDOR / "px4-autopilot"))
    if not px4_dir.is_dir():
        fail(f"PX4 checkout missing: {px4_dir}")
    return px4_dir


def generated_gz_env(px4_dir: Path) -> Path:
    path = px4_dir / "build" / "px4_sitl_default" / "rootfs" / "gz_env.sh"
    if not path.is_file():
        fail(f"PX4 Gazebo environment is missing: {path}; run ./dev setup")
    return path


def source_shell_environment(script: Path, base_env: dict) -> dict:
    result = subprocess.run(
        ["bash", "-c", 'source "$1" >/dev/null 2>&1; env -0', "bash", str(script)],
        env=base_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        fail("could not load PX4 Gazebo environment")

    env: dict[str, str] = {}
    for item in result.stdout.split(b"\0"):
        if not item or b"=" not in item:
            continue
        key, value = item.split(b"=", 1)
        env[key.decode(errors="replace")] = value.decode(errors="replace")
    return env


def gazebo_environment(px4_dir: Path) -> dict:
    base = os.environ.copy()
    base["GZ_PARTITION"] = PARTITION
    base["DRONE_RUNTIME_OWNER"] = OWNER_ID
    env = source_shell_environment(generated_gz_env(px4_dir), base)
    env["GZ_PARTITION"] = PARTITION
    env["DRONE_RUNTIME_OWNER"] = OWNER_ID

    existing = [value for value in env.get("GZ_SIM_RESOURCE_PATH", "").split(":") if value]
    repo_worlds = str(WORLDS.resolve())
    if repo_worlds not in existing:
        existing.insert(0, repo_worlds)
    env["GZ_SIM_RESOURCE_PATH"] = ":".join(existing)
    return env


def validate_world_with_gazebo(world: Path, env: dict) -> None:
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
        fail(f"Gazebo rejected {world.name}:\n{result.stdout.strip()}")


def world_ready(name: str, env: dict) -> bool:
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


def process_environ(pid: int) -> dict[str, str]:
    try:
        raw = Path(f"/proc/{pid}/environ").read_bytes()
    except OSError:
        return {}
    result: dict[str, str] = {}
    for item in raw.split(b"\0"):
        if b"=" in item:
            key, value = item.split(b"=", 1)
            result[key.decode(errors="replace")] = value.decode(errors="replace")
    return result


def process_cmdline(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
    except OSError:
        return ""


def process_cwd(pid: int) -> Path | None:
    try:
        return Path(f"/proc/{pid}/cwd").resolve()
    except OSError:
        return None


def process_pgid(pid: int) -> int | None:
    try:
        return os.getpgid(pid)
    except OSError:
        return None


def gazebo_like_process(pid: int) -> bool:
    command = process_cmdline(pid)
    return "gz sim" in command or "gz-sim" in command or ("ruby" in command and "gz" in command and "sim" in command)


def terminate_pgid(pgid: int | str | None, label: str) -> bool:
    if not pgid_alive(pgid):
        return True
    for sig, timeout in (
        (signal.SIGINT, 3.0),
        (signal.SIGTERM, 2.0),
        (signal.SIGKILL, 1.5),
    ):
        try:
            os.killpg(int(pgid), sig)
        except ProcessLookupError:
            return True
        except (PermissionError, TypeError, ValueError):
            return False
        if wait_for(lambda: not pgid_alive(pgid), timeout):
            say(f"[OK] stopped {label}")
            return True
    return not pgid_alive(pgid)


def terminate_state(path: Path, label: str) -> None:
    state = read_state(path)
    if not state:
        return
    if not state_active(state):
        clear_state(path)
        return
    if terminate_pgid(state.get("pgid"), label):
        clear_state(path)
    else:
        say(f"[WARN] could not stop {label}")


def protected_gazebo_pgids() -> set[int]:
    protected: set[int] = set()
    for path in (SERVER_STATE, GUI_STATE):
        state = read_state(path)
        if state_active(state) and state.get("pgid") is not None:
            protected.add(int(state["pgid"]))
    return protected


def cleanup_owned_orphans() -> int:
    protected = protected_gazebo_pgids()
    terminated: set[int] = set()
    cleaned = 0
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        pid = int(proc.name)
        if process_environ(pid).get("DRONE_RUNTIME_OWNER") != OWNER_ID or not gazebo_like_process(pid):
            continue
        pgid = process_pgid(pid)
        if pgid is None or pgid in protected or pgid in terminated:
            continue
        terminated.add(pgid)
        if terminate_pgid(pgid, f"orphaned managed Gazebo pgid={pgid}"):
            cleaned += 1
    return cleaned


def cleanup_legacy_px4_gazebo(px4_dir: Path) -> int:
    rootfs = (px4_dir / "build" / "px4_sitl_default" / "rootfs").resolve()
    terminated: set[int] = set()
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
        pgid = process_pgid(pid)
        if pgid is None or pgid in terminated:
            continue
        terminated.add(pgid)
        if terminate_pgid(pgid, f"legacy PX4 Gazebo pgid={pgid}"):
            cleaned += 1
    return cleaned


def start_server(name: str, world: Path, env: dict) -> None:
    tracked = read_state(SERVER_STATE)
    if state_active(tracked):
        if tracked.get("scenario") != name:
            fail("another scenario is already running; use ./mission stop")
        if world_ready(name, env):
            say(f"[OK] Gazebo world ready: {name}")
            return
        terminate_state(SERVER_STATE, "unhealthy Gazebo server")
    else:
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
    if not wait_for(lambda: state_active(state) and world_ready(name, env), 20.0, 0.35):
        terminate_state(SERVER_STATE, "Gazebo server")
        cleanup_owned_orphans()
        tail = "\n".join(SERVER_LOG.read_text(errors="replace").splitlines()[-30:]) if SERVER_LOG.exists() else ""
        fail(f"Gazebo world {name!r} did not become ready.\n{tail}")
    say(f"[OK] Gazebo world ready: {name}")


def start_gui(env: dict) -> None:
    tracked = read_state(GUI_STATE)
    if state_active(tracked):
        say("[OK] Gazebo GUI ready")
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
    if not wait_for(lambda: state_active(state), 2.0):
        clear_state(GUI_STATE)
        cleanup_owned_orphans()
        fail("Gazebo GUI exited immediately; run ./mission logs")
    say("[OK] Gazebo GUI ready")


def start(name: str) -> None:
    ensure_dirs()
    world = validate_scenario(name)
    px4_dir = resolved_px4_dir()
    env = gazebo_environment(px4_dir)
    validate_world_with_gazebo(world, env)

    server = read_state(SERVER_STATE)
    if state_active(server):
        if server.get("scenario") != name:
            fail("another scenario is already running; use ./mission stop")
        if world_ready(name, env):
            start_gui(env)
            say(f"[OK] Gazebo ready: {name}")
            return
        terminate_state(GUI_STATE, "Gazebo GUI")
        terminate_state(SERVER_STATE, "unhealthy Gazebo server")

    terminate_state(GUI_STATE, "stale Gazebo GUI")
    cleanup_owned_orphans()
    cleanup_legacy_px4_gazebo(px4_dir)
    start_server(name, world, env)
    start_gui(env)
    say(f"[OK] Gazebo ready: {name}")


def stop() -> None:
    ensure_dirs()
    terminate_state(GUI_STATE, "Gazebo GUI")
    terminate_state(SERVER_STATE, "Gazebo server")
    cleanup_owned_orphans()
    try:
        px4_dir = resolved_px4_dir()
    except SystemExit:
        px4_dir = None
    if px4_dir is not None:
        cleanup_legacy_px4_gazebo(px4_dir)


def status() -> None:
    server = read_state(SERVER_STATE)
    gui = read_state(GUI_STATE)
    say(f"Gazebo      : {'RUNNING' if state_active(server) else 'STOPPED'}")
    if state_active(server):
        say(f"Gazebo world: {server.get('scenario', '?')}")
    say(f"Gazebo GUI  : {'RUNNING' if state_active(gui) else 'STOPPED'}")


def logs() -> None:
    for path in (SERVER_LOG, GUI_LOG):
        say(f"\n===== {path.relative_to(ROOT)} =====")
        if not path.exists():
            say("(no log yet)")
            continue
        say("\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]))
