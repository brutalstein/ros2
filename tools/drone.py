#!/usr/bin/env python3
from __future__ import annotations

import fcntl
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import bootstrap

ROOT = bootstrap.ROOT
RUNTIME = bootstrap.WORKSPACE / "runtime"
LOGS = RUNTIME / "logs"
LOCK = RUNTIME / "runtime.lock"
AGENT_STATE = RUNTIME / "agent.json"
PX4_STATE = RUNTIME / "px4.json"
AGENT_LOG = LOGS / "microxrce-agent.log"
PX4_LOG = LOGS / "px4.log"


def say(message=""):
    print(message, flush=True)


def fail(message):
    raise SystemExit(f"[FAIL] {message}")


def ensure_dirs():
    bootstrap.ensure_dirs()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)


def manifest():
    return bootstrap.load_manifest()


def ensure_ready():
    m = manifest()
    info = bootstrap.detect_platform()
    if not bootstrap.verify(m, info, strict=False):
        say("[INFO] runtime dependencies are missing/drifted; repairing automatically")
        bootstrap.setup(m)
    return m, bootstrap.detect_platform(), bootstrap.load_state()


def process_start_ticks(pid):
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    end = text.rfind(")")
    fields = text[end + 2 :].split() if end >= 0 else []
    return fields[19] if len(fields) > 19 else None


def identity(pid, kind, **extra):
    return {"pid": pid, "start_ticks": process_start_ticks(pid), "kind": kind, "owned": True, **extra}


def alive(state):
    if not state:
        return False
    try:
        pid = int(state["pid"])
    except (KeyError, TypeError, ValueError):
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return process_start_ticks(pid) == state.get("start_ticks")


def read_state(path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def write_state(path, data):
    ensure_dirs()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


def clear_state(path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def udp_bound(port):
    wanted = f"{port:04X}"
    for table in (Path("/proc/net/udp"), Path("/proc/net/udp6")):
        try:
            lines = table.read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) > 1 and ":" in fields[1] and fields[1].rsplit(":", 1)[1].upper() == wanted:
                return True
    return False


def wait_for(predicate, seconds, interval=0.1):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def state_paths(state, m):
    resolved = state.get("resolved", {})
    px4_dir = Path(resolved.get("px4_dir", bootstrap.VENDOR / "px4-autopilot"))
    agent_bin = Path(
        resolved.get(
            "micro_xrce_dds_agent_binary",
            bootstrap.DEPS / "micro-xrce-dds-agent" / "bin" / "MicroXRCEAgent",
        )
    )
    port = int(resolved.get("dds_port", m["stack"]["micro_xrce_dds_agent"]["port"]))
    return px4_dir, agent_bin, port


def start_agent(agent_bin, port):
    tracked = read_state(AGENT_STATE)
    if alive(tracked) and udp_bound(port):
        say(f"[OK] DDS Agent already running on UDP {port} (pid {tracked['pid']})")
        return
    if tracked:
        clear_state(AGENT_STATE)
    if udp_bound(port):
        fail(f"UDP {port} is already occupied by an unmanaged process; refusing to take it over")
    if not agent_bin.is_file():
        fail(f"managed MicroXRCEAgent binary missing: {agent_bin}")

    env = os.environ.copy()
    local_lib = str(agent_bin.parent.parent / "lib")
    env["LD_LIBRARY_PATH"] = local_lib + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")
    with AGENT_LOG.open("a") as log:
        log.write(f"\n===== {time.strftime('%F %T')} start UDP {port} =====\n")
        log.flush()
        process = subprocess.Popen(
            [str(agent_bin), "udp4", "-p", str(port)],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=env,
        )
    item = identity(process.pid, "microxrce-agent", port=port)
    write_state(AGENT_STATE, item)
    if not wait_for(lambda: alive(item) and udp_bound(port), 6.0):
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except OSError:
            pass
        clear_state(AGENT_STATE)
        fail(f"DDS Agent did not bind UDP {port}; inspect ./drone logs")
    say(f"[OK] DDS Agent background service ready on UDP {port}")


def terminal_command(info, linux_command):
    if info["wsl2"]:
        cmd = shutil.which("cmd.exe") or "/mnt/c/Windows/System32/cmd.exe"
        if not Path(cmd).exists() and not shutil.which("cmd.exe"):
            return None
        distro = info.get("wsl_distro")
        wsl = ["wsl.exe"]
        if distro:
            wsl += ["-d", distro]
        wsl += ["--", "bash", "-lc", linux_command]
        return [cmd, "/c", "start", "", "wt.exe", "new-tab", "--title", "PX4 + Gazebo", *wsl]

    if shutil.which("gnome-terminal"):
        return ["gnome-terminal", "--", "bash", "-lc", linux_command]
    if shutil.which("konsole"):
        return ["konsole", "-e", "bash", "-lc", linux_command]
    if shutil.which("x-terminal-emulator"):
        return ["x-terminal-emulator", "-e", "bash", "-lc", linux_command]
    return None


def launch_px4(info):
    tracked = read_state(PX4_STATE)
    if alive(tracked):
        say(f"[OK] PX4 + Gazebo already running (pid {tracked['pid']})")
        return

    linux_command = f"cd {shlex.quote(str(ROOT))} && exec ./drone _px4-run"
    cmd = terminal_command(info, linux_command)
    if cmd is None:
        say("[WARN] no terminal launcher detected; PX4 will run in background and log to .workspace/runtime/logs/px4.log")
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "_px4-background"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    else:
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, check=False)
        if result.returncode != 0:
            fail("could not open PX4 terminal: " + result.stderr.strip())

    if not wait_for(lambda: alive(read_state(PX4_STATE)), 15.0, 0.2):
        fail("PX4 runtime did not register within 15 seconds; inspect ./drone logs")
    state = read_state(PX4_STATE)
    say(f"[OK] PX4 + Gazebo started (pid {state['pid']})")


def px4_process(background=False):
    m = manifest()
    state = bootstrap.load_state()
    px4_dir, _, _ = state_paths(state, m)
    target = os.environ.get("PX4_SIM_TARGET", m["stack"]["px4"]["sim_target"])
    if not px4_dir.is_dir():
        fail(f"PX4 checkout missing: {px4_dir}")

    output = None
    if background:
        output = PX4_LOG.open("a")
        output.write(f"\n===== {time.strftime('%F %T')} start target={target} =====\n")
        output.flush()

    process = subprocess.Popen(
        ["make", "px4_sitl", target],
        cwd=px4_dir,
        stdin=None if not background else subprocess.DEVNULL,
        stdout=None if not background else output,
        stderr=None if not background else subprocess.STDOUT,
        start_new_session=True,
    )
    item = identity(process.pid, "px4-sitl", target=target, px4_dir=str(px4_dir))
    write_state(PX4_STATE, item)
    try:
        returncode = process.wait()
        if returncode:
            say(f"[WARN] PX4 exited with code {returncode}")
    finally:
        clear_state(PX4_STATE)
        if output:
            output.close()


def terminate(path, label):
    state = read_state(path)
    if not state:
        return
    if not alive(state):
        clear_state(path)
        return
    pid = int(state["pid"])
    for sig, timeout in ((signal.SIGINT, 5), (signal.SIGTERM, 3)):
        try:
            os.killpg(pid, sig)
        except OSError:
            pass
        if wait_for(lambda: not alive(state), timeout):
            say(f"[OK] stopped {label}")
            clear_state(path)
            return
    say(f"[WARN] {label} did not stop cleanly; SIGKILL was intentionally not used")


def start():
    ensure_dirs()
    m, info, state = ensure_ready()
    _, agent_bin, port = state_paths(state, m)
    with LOCK.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        start_agent(agent_bin, port)
        launch_px4(info)
    say("[OK] simulation runtime ready")
    say("Use another terminal: ./ros topics  or  ./dev r <node>")


def stop():
    ensure_dirs()
    with LOCK.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        terminate(PX4_STATE, "PX4 + Gazebo")
        terminate(AGENT_STATE, "DDS Agent")


def status():
    m = manifest()
    state = bootstrap.load_state()
    _, _, port = state_paths(state, m)
    agent = read_state(AGENT_STATE)
    px4 = read_state(PX4_STATE)
    say(f"DDS Agent : {'RUNNING' if alive(agent) else 'STOPPED'} | UDP {port} {'BOUND' if udp_bound(port) else 'FREE'}")
    say(f"PX4/Gazebo: {'RUNNING' if alive(px4) else 'STOPPED'}")
    if alive(px4):
        say(f"PX4 target : {px4.get('target', '?')}")


def logs(follow=False):
    paths = [AGENT_LOG, PX4_LOG]
    if follow:
        existing = [str(p) for p in paths if p.exists()]
        if not existing:
            say("No runtime logs yet.")
            return
        os.execvp("tail", ["tail", "-n", "60", "-F", *existing])
    for path in paths:
        say(f"\n===== {path.relative_to(ROOT)} =====")
        if not path.exists():
            say("(no log yet)")
            continue
        lines = path.read_text(errors="replace").splitlines()[-60:]
        say("\n".join(lines))


def doctor():
    m = manifest()
    bootstrap.doctor(m)
    state = bootstrap.load_state()
    if state:
        _, agent, port = state_paths(state, m)
        say(f"[{'OK' if agent.exists() else '--'}] managed Agent: {agent}")
        say(f"[INFO] DDS port: {port}")
    status()


def help_text():
    say('''Usage:
  ./drone start        auto-repair dependencies, start DDS Agent + PX4/Gazebo
  ./drone stop         stop processes started by this runtime
  ./drone status       show runtime status
  ./drone logs         show recent runtime logs
  ./drone logs -f      follow runtime logs
  ./drone doctor       platform/toolchain/runtime diagnostics

Overrides:
  PX4_SIM_TARGET=gz_x500_depth ./drone start
''')


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "help"
    if cmd == "start":
        start()
    elif cmd == "stop":
        stop()
    elif cmd == "status":
        status()
    elif cmd == "logs":
        logs("-f" in args[1:] or "--follow" in args[1:])
    elif cmd == "doctor":
        doctor()
    elif cmd == "_px4-run":
        px4_process(background=False)
    elif cmd == "_px4-background":
        px4_process(background=True)
    elif cmd in {"help", "-h", "--help"}:
        help_text()
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
