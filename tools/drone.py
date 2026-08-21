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

import workspace_layout as layout

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_DIR = layout.STATE_DIR / "runtime"
RUNTIME_LOG_DIR = RUNTIME_DIR / "logs"
LOCK_FILE = RUNTIME_DIR / "drone.lock"
AGENT_STATE = RUNTIME_DIR / "agent.json"
PX4_STATE = RUNTIME_DIR / "px4.json"
AGENT_LOG = RUNTIME_LOG_DIR / "microxrce_agent.log"

PX4_DIR = Path(
    os.environ.get("PX4_AUTOPILOT_DIR", str(Path.home() / "PX4-Autopilot"))
).expanduser().resolve()
PX4_TARGET = os.environ.get("PX4_SIM_TARGET", "gz_x500")
DDS_PORT = int(os.environ.get("XRCE_DDS_PORT", "8888"))
WSL_DISTRO = os.environ.get("WSL_DISTRO_NAME", "").strip()


def say(message=""):
    print(message, flush=True)


def die(message, code=1):
    raise SystemExit(f"[FAIL] {message}")


def ensure_runtime_dirs():
    layout.ensure()
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    RUNTIME_LOG_DIR.mkdir(parents=True, exist_ok=True)


def is_wsl():
    try:
        text = Path("/proc/version").read_text(encoding="utf-8", errors="ignore").lower()
    except OSError:
        return False
    return "microsoft" in text or bool(os.environ.get("WSL_INTEROP"))


def process_start_ticks(pid: int):
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None

    end = text.rfind(")")
    if end < 0:
        return None
    fields = text[end + 2 :].split()
    if len(fields) <= 19:
        return None
    return fields[19]


def process_args(pid: int):
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return []
    return [item.decode(errors="replace") for item in raw.split(b"\0") if item]


def process_cwd(pid: int):
    try:
        return Path(os.readlink(f"/proc/{pid}/cwd"))
    except OSError:
        return None


def process_identity(pid: int, *, owned: bool, kind: str, **extra):
    return {
        "pid": pid,
        "start_ticks": process_start_ticks(pid),
        "owned": owned,
        "kind": kind,
        **extra,
    }


def identity_alive(identity):
    if not identity:
        return False
    try:
        pid = int(identity["pid"])
    except (KeyError, TypeError, ValueError):
        return False

    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False

    expected = identity.get("start_ticks")
    current = process_start_ticks(pid)
    return expected is not None and current == expected


def load_state(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def write_state(path: Path, data):
    ensure_runtime_dirs()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def clear_state(path: Path):
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def iter_processes():
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            yield int(entry.name)


def udp_port_bound(port: int):
    wanted = f"{port:04X}"
    for table in (Path("/proc/net/udp"), Path("/proc/net/udp6")):
        try:
            lines = table.read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 2 or ":" not in fields[1]:
                continue
            if fields[1].rsplit(":", 1)[1].upper() == wanted:
                return True
    return False


def wait_until(predicate, timeout: float, interval: float = 0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def resolve_agent_binary():
    override = os.environ.get("MICRO_XRCE_AGENT_BIN")
    candidates = []
    if override:
        candidates.append(Path(override).expanduser())

    from_path = shutil.which("MicroXRCEAgent")
    if from_path:
        candidates.append(Path(from_path))

    candidates.extend(
        [
            Path.home() / "Micro-XRCE-DDS-Agent" / "build" / "MicroXRCEAgent",
            Path.home() / "Micro-XRCE-DDS-Agent" / "build" / "src" / "MicroXRCEAgent",
        ]
    )

    for candidate in candidates:
        try:
            candidate = candidate.resolve()
        except OSError:
            continue
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def is_agent_process(pid: int):
    args = process_args(pid)
    if not args or "MicroXRCEAgent" not in Path(args[0]).name:
        return False
    if "udp4" not in args:
        return False
    try:
        index = args.index("-p")
        return index + 1 < len(args) and int(args[index + 1]) == DDS_PORT
    except (ValueError, TypeError):
        return False


def find_agent_process():
    for pid in iter_processes():
        if is_agent_process(pid):
            return pid
    return None


def tail(path: Path, lines=20):
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(content[-lines:])


def ensure_agent():
    tracked = load_state(AGENT_STATE)
    if identity_alive(tracked) and is_agent_process(int(tracked["pid"])):
        if wait_until(lambda: udp_port_bound(DDS_PORT), 1.0):
            say(f"[OK] Micro XRCE-DDS Agent already running on UDP {DDS_PORT} (pid {tracked['pid']})")
            return False

    if tracked:
        clear_state(AGENT_STATE)

    existing = find_agent_process()
    if existing is not None:
        identity = process_identity(
            existing,
            owned=False,
            kind="microxrce_agent",
            port=DDS_PORT,
        )
        write_state(AGENT_STATE, identity)
        if not wait_until(lambda: udp_port_bound(DDS_PORT), 2.0):
            die(f"MicroXRCEAgent pid {existing} exists but UDP {DDS_PORT} is not bound")
        say(f"[OK] reusing existing Micro XRCE-DDS Agent on UDP {DDS_PORT} (pid {existing})")
        return False

    if udp_port_bound(DDS_PORT):
        die(
            f"UDP port {DDS_PORT} is already in use by an unknown process. "
            "Automation will not take over or kill it."
        )

    binary = resolve_agent_binary()
    if binary is None:
        die(
            "MicroXRCEAgent was not found. Expected it in PATH or under "
            "~/Micro-XRCE-DDS-Agent/build/MicroXRCEAgent."
        )

    ensure_runtime_dirs()
    with AGENT_LOG.open("a", encoding="utf-8") as log:
        log.write(f"\n===== start {time.strftime('%Y-%m-%d %H:%M:%S')} port={DDS_PORT} =====\n")
        log.flush()
        process = subprocess.Popen(
            [str(binary), "udp4", "-p", str(DDS_PORT)],
            cwd=binary.parent,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    identity = process_identity(
        process.pid,
        owned=True,
        kind="microxrce_agent",
        port=DDS_PORT,
        executable=str(binary),
    )
    write_state(AGENT_STATE, identity)

    ready = wait_until(
        lambda: identity_alive(identity) and udp_port_bound(DDS_PORT),
        5.0,
    )
    if not ready:
        if identity_alive(identity):
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        clear_state(AGENT_STATE)
        detail = tail(AGENT_LOG, 25)
        suffix = f"\n\nAgent log:\n{detail}" if detail else ""
        die(f"Micro XRCE-DDS Agent did not become ready on UDP {DDS_PORT}.{suffix}")

    say(f"[OK] Micro XRCE-DDS Agent ready in background on UDP {DDS_PORT} (pid {process.pid})")
    say(f"[OK] Agent log: {AGENT_LOG.relative_to(ROOT)}")
    return True


def validate_px4_checkout():
    if not PX4_DIR.is_dir():
        die(f"PX4 checkout not found: {PX4_DIR}")
    if not (PX4_DIR / "Makefile").is_file():
        die(f"PX4 Makefile not found: {PX4_DIR / 'Makefile'}")
    if shutil.which("make") is None:
        die("make is not installed")


def is_px4_process(pid: int):
    args = process_args(pid)
    if not args:
        return False
    joined = " ".join(args)
    if "px4_sitl_default/bin/px4" not in joined:
        return False

    cwd = process_cwd(pid)
    if cwd is None:
        return True
    try:
        cwd.resolve().relative_to(PX4_DIR)
        return True
    except (ValueError, OSError):
        return str(PX4_DIR) in joined


def find_px4_process():
    for pid in iter_processes():
        if is_px4_process(pid):
            return pid
    return None


def tracked_px4_running():
    state = load_state(PX4_STATE)
    if identity_alive(state):
        return state
    if state:
        clear_state(PX4_STATE)
    return None


def find_windows_launcher():
    wt = shutil.which("wt.exe")
    if wt:
        return "wt", wt

    cmd = shutil.which("cmd.exe")
    if cmd:
        return "cmd", cmd

    system_cmd = Path("/mnt/c/Windows/System32/cmd.exe")
    if system_cmd.is_file():
        return "cmd", str(system_cmd)

    return None, None


def launch_px4_terminal():
    tracked = tracked_px4_running()
    if tracked:
        say(f"[OK] PX4 launcher already running (pid {tracked['pid']})")
        return False

    existing = find_px4_process()
    if existing is not None:
        say(f"[OK] PX4 SITL already running (external pid {existing}); no duplicate launched")
        return False

    if not is_wsl():
        die("./drone start currently expects WSL because it opens a Windows terminal for PX4")

    kind, launcher = find_windows_launcher()
    if launcher is None:
        die("Windows Terminal/cmd launcher was not found from WSL")

    distro_args = ["-d", WSL_DISTRO] if WSL_DISTRO else []
    linux_command = f"cd {shlex.quote(str(ROOT))} && exec ./drone _px4-run"
    wsl_command = ["wsl.exe", *distro_args, "--", "bash", "-lc", linux_command]

    if kind == "wt":
        command = [
            launcher,
            "-w", "new",
            "new-tab",
            "--title", "PX4 + Gazebo",
            *wsl_command,
        ]
    else:
        command = [launcher, "/c", "start", "", *wsl_command]

    result = subprocess.run(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or "").strip()
        die(f"failed to open PX4 terminal{': ' + detail if detail else ''}")

    if not wait_until(lambda: tracked_px4_running() is not None, 10.0, 0.2):
        die(
            "PX4 terminal was requested but its runtime process did not register within 10 seconds. "
            "Check whether Windows Terminal opened correctly."
        )

    state = tracked_px4_running()
    say(f"[OK] PX4 + Gazebo opened in a new terminal (pid {state['pid']})")
    return True


def px4_run_internal():
    ensure_runtime_dirs()
    validate_px4_checkout()

    existing = find_px4_process()
    if existing is not None:
        say(f"[OK] PX4 SITL is already running (pid {existing})")
        return

    identity = process_identity(
        os.getpid(),
        owned=True,
        kind="px4_launcher",
        target=PX4_TARGET,
        px4_dir=str(PX4_DIR),
    )
    write_state(PX4_STATE, identity)

    say(f"[INFO] PX4 checkout: {PX4_DIR}")
    say(f"[INFO] simulation target: {PX4_TARGET}")
    say(f"[INFO] DDS Agent expected on UDP {DDS_PORT}")
    say("[INFO] starting PX4 SITL + Gazebo...")

    os.chdir(PX4_DIR)
    try:
        os.execvp("make", ["make", "px4_sitl", PX4_TARGET])
    except OSError as exc:
        clear_state(PX4_STATE)
        die(f"could not execute PX4 build/run command: {exc}")


def terminate_identity(identity, *, name: str, timeout=5.0, process_group=False):
    if not identity_alive(identity):
        return True

    pid = int(identity["pid"])
    if not identity.get("owned"):
        say(f"[INFO] {name} pid {pid} was not started by ./drone; leaving it running")
        return False

    def send(sig):
        try:
            if process_group:
                os.killpg(pid, sig)
            else:
                os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            pass

    send(signal.SIGINT)
    if wait_until(lambda: not identity_alive(identity), timeout, 0.1):
        say(f"[OK] stopped {name}")
        return True

    send(signal.SIGTERM)
    if wait_until(lambda: not identity_alive(identity), 3.0, 0.1):
        say(f"[OK] stopped {name}")
        return True

    say(f"[WARN] {name} pid {pid} did not stop cleanly; no SIGKILL was sent")
    return False


def stop_agent_if_owned():
    state = load_state(AGENT_STATE)
    if not state:
        return
    if identity_alive(state):
        terminate_identity(state, name="Micro XRCE-DDS Agent", process_group=True)
    clear_state(AGENT_STATE)


def start():
    ensure_runtime_dirs()
    if not is_wsl():
        die("./drone start currently supports the WSL runtime used by this project")

    with LOCK_FILE.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        validate_px4_checkout()
        agent_started_here = ensure_agent()
        try:
            launch_px4_terminal()
        except BaseException:
            if agent_started_here:
                say("[INFO] PX4 launch failed; rolling back the Agent started by this command")
                stop_agent_if_owned()
            raise

    say("")
    say("[READY] PX4/Gazebo runtime is starting and DDS transport is ready")
    say("[READY] Open your ROS terminal separately and use ./ros or ./dev r ...")


def stop():
    ensure_runtime_dirs()
    with LOCK_FILE.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)

        px4 = load_state(PX4_STATE)
        if px4 and identity_alive(px4):
            terminate_identity(px4, name="PX4 launcher", process_group=False)
        elif find_px4_process() is not None:
            say("[INFO] an untracked PX4 SITL process is running; leaving it untouched")
        else:
            say("[OK] PX4 launcher is not running")
        clear_state(PX4_STATE)

        agent = load_state(AGENT_STATE)
        if agent and identity_alive(agent):
            terminate_identity(agent, name="Micro XRCE-DDS Agent", process_group=bool(agent.get("owned")))
        elif find_agent_process() is not None:
            say("[INFO] an untracked MicroXRCEAgent is running; leaving it untouched")
        else:
            say("[OK] Micro XRCE-DDS Agent is not running")
        clear_state(AGENT_STATE)


def status():
    ensure_runtime_dirs()

    agent = load_state(AGENT_STATE)
    if agent and identity_alive(agent):
        owner = "managed" if agent.get("owned") else "external"
        say(f"[OK] Agent: running ({owner}, pid {agent['pid']}, UDP {DDS_PORT})")
    else:
        external_agent = find_agent_process()
        if external_agent is not None:
            say(f"[OK] Agent: running (external, pid {external_agent}, UDP {DDS_PORT})")
        else:
            say("[--] Agent: stopped")

    say(f"[{'OK' if udp_port_bound(DDS_PORT) else '--'}] UDP {DDS_PORT}: {'bound' if udp_port_bound(DDS_PORT) else 'free'}")

    px4 = tracked_px4_running()
    if px4:
        say(f"[OK] PX4 launcher: running (pid {px4['pid']}, target {px4.get('target', PX4_TARGET)})")
    else:
        external_px4 = find_px4_process()
        if external_px4 is not None:
            say(f"[OK] PX4 SITL: running (external pid {external_px4})")
        else:
            say("[--] PX4 SITL: stopped")

    gazebo = any(
        "gz sim" in " ".join(process_args(pid)) or "gz-sim" in " ".join(process_args(pid))
        for pid in iter_processes()
    )
    say(f"[{'OK' if gazebo else '--'}] Gazebo: {'running' if gazebo else 'not detected'}")
    say(f"[INFO] Agent log: {AGENT_LOG.relative_to(ROOT)}")


def doctor():
    ensure_runtime_dirs()
    binary = resolve_agent_binary()
    launcher_kind, launcher = find_windows_launcher()

    checks = [
        ("WSL", is_wsl(), os.environ.get("WSL_DISTRO_NAME", "detected") if is_wsl() else "not detected"),
        ("PX4 checkout", PX4_DIR.is_dir() and (PX4_DIR / "Makefile").is_file(), str(PX4_DIR)),
        ("make", shutil.which("make") is not None, shutil.which("make") or "missing"),
        ("MicroXRCEAgent", binary is not None, str(binary) if binary else "missing"),
        ("Windows terminal launcher", launcher is not None, f"{launcher_kind}: {launcher}" if launcher else "missing"),
    ]

    failed = 0
    for label, ok, detail in checks:
        say(f"[{'OK' if ok else '--'}] {label}: {detail}")
        failed += 0 if ok else 1

    if udp_port_bound(DDS_PORT):
        agent = find_agent_process()
        if agent is None:
            say(f"[WARN] UDP {DDS_PORT} is occupied by an unknown process")
            failed += 1
        else:
            say(f"[OK] UDP {DDS_PORT}: MicroXRCEAgent pid {agent}")
    else:
        say(f"[OK] UDP {DDS_PORT}: available")

    if failed:
        die(f"{failed} runtime prerequisite(s) need attention")
    say("[OK] drone runtime prerequisites are ready")


def logs(follow=False):
    ensure_runtime_dirs()
    if not AGENT_LOG.exists():
        say("No Agent log yet. Run ./drone start first.")
        return

    if follow:
        os.execvp("tail", ["tail", "-n", "80", "-f", str(AGENT_LOG)])
    content = tail(AGENT_LOG, 80)
    say(content or "(empty log)")


def help_text():
    say(
        """Drone runtime console

  ./drone start        start/reuse DDS Agent, then open PX4 + Gazebo in a new WSL terminal
  ./drone status       show Agent, UDP port, PX4 and Gazebo runtime state
  ./drone stop         gracefully stop only processes owned by this console
  ./drone logs         show recent background Agent logs
  ./drone logs -f      follow background Agent logs
  ./drone doctor       validate WSL/PX4/Agent/terminal prerequisites

Environment overrides
  PX4_AUTOPILOT_DIR    PX4 checkout (default: ~/PX4-Autopilot)
  PX4_SIM_TARGET       PX4 simulation target (default: gz_x500)
  XRCE_DDS_PORT        Micro XRCE-DDS UDP port (default: 8888)
  MICRO_XRCE_AGENT_BIN explicit MicroXRCEAgent executable
"""
    )


def main():
    command = sys.argv[1] if len(sys.argv) > 1 else "help"
    rest = sys.argv[2:]

    if command == "start":
        if rest:
            die("usage: ./drone start")
        start()
    elif command == "status":
        if rest:
            die("usage: ./drone status")
        status()
    elif command == "stop":
        if rest:
            die("usage: ./drone stop")
        stop()
    elif command == "logs":
        if rest not in ([], ["-f"], ["--follow"]):
            die("usage: ./drone logs [-f]")
        logs(follow=bool(rest))
    elif command == "doctor":
        if rest:
            die("usage: ./drone doctor")
        doctor()
    elif command == "_px4-run":
        px4_run_internal()
    elif command in {"help", "-h", "--help"}:
        help_text()
    else:
        die(f"unknown command: {command}\nRun ./drone help")


if __name__ == "__main__":
    main()
