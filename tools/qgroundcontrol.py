#!/usr/bin/env python3
from __future__ import annotations

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
STATE_FILE = RUNTIME / "qgroundcontrol.json"
LOG_FILE = LOGS / "qgroundcontrol.log"
STATUS_TOPIC = "/fmu/out/vehicle_status_v1"


def say(message: str = "") -> None:
    print(message, flush=True)


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] {message}")


def config(manifest: dict | None = None) -> dict:
    manifest = manifest or bootstrap.load_manifest()
    return manifest["stack"]["qgroundcontrol"]


def binary_path(manifest: dict | None = None) -> Path:
    spec = config(manifest)
    return bootstrap.DEPS / "qgroundcontrol" / spec["version"] / spec["filename"]


def ensure_dirs() -> None:
    bootstrap.ensure_dirs()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)


def setup() -> Path:
    ensure_dirs()
    manifest = bootstrap.load_manifest()
    spec = config(manifest)

    if not spec.get("enabled", True):
        fail("QGroundControl is disabled in toolchain.json")

    bootstrap.apt_install_missing(spec.get("apt_packages", []))

    target = binary_path(manifest)
    target.parent.mkdir(parents=True, exist_ok=True)
    minimum_bytes = int(spec.get("minimum_bytes", 1_000_000))

    if target.is_file() and target.stat().st_size >= minimum_bytes:
        target.chmod(0o755)
        say(f"[OK] QGroundControl {spec['version']} already installed")
        return target

    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)

    say(f"[INFO] downloading QGroundControl {spec['version']}")
    bootstrap.run([
        "curl",
        "-fL",
        "--retry", "3",
        "--retry-delay", "2",
        "-o", partial,
        spec["download_url"],
    ])

    if not partial.is_file() or partial.stat().st_size < minimum_bytes:
        partial.unlink(missing_ok=True)
        fail("QGroundControl download is missing or unexpectedly small")

    partial.chmod(0o755)
    os.replace(partial, target)
    say(f"[OK] QGroundControl installed: {target.relative_to(ROOT)}")
    return target


def process_start_ticks(pid: int) -> str | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None

    end = text.rfind(")")
    fields = text[end + 2 :].split() if end >= 0 else []
    return fields[19] if len(fields) > 19 else None


def identity(pid: int) -> dict:
    return {
        "pid": pid,
        "start_ticks": process_start_ticks(pid),
        "kind": "qgroundcontrol",
        "owned": True,
    }


def read_state() -> dict | None:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def write_state(state: dict) -> None:
    ensure_dirs()
    temp = STATE_FILE.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, STATE_FILE)


def clear_state() -> None:
    STATE_FILE.unlink(missing_ok=True)


def alive(state: dict | None = None) -> bool:
    state = state or read_state()
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


def udp_bound(port: int) -> bool:
    wanted = f"{port:04X}"
    for table in (Path("/proc/net/udp"), Path("/proc/net/udp6")):
        try:
            lines = table.read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            continue

        for line in lines:
            fields = line.split()
            if len(fields) <= 1 or ":" not in fields[1]:
                continue
            if fields[1].rsplit(":", 1)[1].upper() == wanted:
                return True

    return False


def wait_for(predicate, seconds: float, interval: float = 0.2) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def display_available() -> bool:
    info = bootstrap.detect_platform()
    if info["wsl2"]:
        return bool(info["wslg"])
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def start() -> None:
    ensure_dirs()
    manifest = bootstrap.load_manifest()
    spec = config(manifest)
    port = int(spec["udp_port"])

    tracked = read_state()
    if alive(tracked):
        say(f"[OK] QGroundControl already running | pid={tracked['pid']}")
        return
    if tracked:
        clear_state()

    if not display_available():
        fail("QGroundControl needs a GUI display; WSL2 users must have WSLg enabled")

    if udp_bound(port):
        fail(f"UDP {port} is already occupied by an unmanaged process; close the other GCS first")

    binary = setup()
    command = [str(binary)]

    # Some WSL installations do not expose /dev/fuse. Type-2 AppImages can
    # still run by extracting themselves for the current process.
    if bootstrap.detect_platform()["wsl2"] and not Path("/dev/fuse").exists():
        command.append("--appimage-extract-and-run")

    with LOG_FILE.open("a", encoding="utf-8") as log:
        log.write(f"\n===== {time.strftime('%F %T')} QGroundControl start =====\n")
        log.flush()
        process = subprocess.Popen(
            command,
            cwd=binary.parent,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=os.environ.copy(),
        )

    state = identity(process.pid)
    write_state(state)

    timeout = float(spec.get("launch_timeout_seconds", 20))
    if not wait_for(lambda: alive(state) and udp_bound(port), timeout):
        if not alive(state):
            clear_state()
        fail(f"QGroundControl did not become ready on UDP {port}; inspect ./drone logs")

    say(f"[OK] QGroundControl running | pid={process.pid} | UDP {port}")


def terminate() -> None:
    state = read_state()
    if not state:
        return
    if not alive(state):
        clear_state()
        return

    pid = int(state["pid"])
    for sig, timeout in ((signal.SIGINT, 4.0), (signal.SIGTERM, 3.0)):
        try:
            os.killpg(pid, sig)
        except OSError:
            pass

        if wait_for(lambda: not alive(state), timeout):
            clear_state()
            say("[OK] stopped QGroundControl")
            return

    say("[WARN] QGroundControl did not stop cleanly; leaving the process untouched")


def read_vehicle_status(timeout: float = 2.5) -> dict[str, str]:
    manifest = bootstrap.load_manifest()
    try:
        env = bootstrap.ros_environment(manifest, include_workspace=True)
    except SystemExit:
        return {}

    command = [
        "ros2", "topic", "echo", STATUS_TOPIC, "--once",
        "--qos-reliability", "best_effort",
        "--qos-durability", "volatile",
    ]

    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {}

    if result.returncode != 0:
        return {}

    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        if key and " " not in key:
            values[key] = value.strip()
    return values


def gcs_connected() -> bool:
    status = read_vehicle_status()
    return status.get("gcs_connection_lost", "true").lower() == "false"


def wait_connected() -> None:
    manifest = bootstrap.load_manifest()
    spec = config(manifest)
    timeout = float(spec.get("connection_timeout_seconds", 30))

    if not alive():
        fail("QGroundControl is not running")

    say("[INFO] waiting for PX4 <-> QGroundControl MAVLink connection")
    if not wait_for(gcs_connected, timeout, 0.5):
        fail("QGroundControl is open but PX4 still reports the GCS connection as lost")

    say("[OK] PX4 <-> QGroundControl connected")


def status() -> None:
    manifest = bootstrap.load_manifest()
    spec = config(manifest)
    port = int(spec["udp_port"])
    state = read_state()
    running = alive(state)

    say(
        f"QGroundControl: {'RUNNING' if running else 'STOPPED'} | "
        f"UDP {port} {'BOUND' if udp_bound(port) else 'FREE'}"
    )

    if running:
        vehicle = read_vehicle_status(timeout=1.5)
        if vehicle:
            connected = vehicle.get("gcs_connection_lost", "true").lower() == "false"
            say(f"QGC/PX4 link : {'CONNECTED' if connected else 'DISCONNECTED'}")


def logs() -> None:
    if not LOG_FILE.exists():
        say("(no QGroundControl log yet)")
        return
    lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
    say("\n".join(lines))


def help_text() -> None:
    say(
        """Usage:
  qgroundcontrol.py setup            install the managed QGroundControl AppImage
  qgroundcontrol.py start            launch QGroundControl
  qgroundcontrol.py wait-connected   wait until PX4 sees the GCS link
  qgroundcontrol.py status           show process/link status
  qgroundcontrol.py stop             stop managed QGroundControl
  qgroundcontrol.py logs             show recent QGroundControl logs
"""
    )


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "help"

    if command == "setup":
        setup()
    elif command == "start":
        start()
    elif command == "wait-connected":
        wait_connected()
    elif command == "status":
        status()
    elif command == "stop":
        terminate()
    elif command == "logs":
        logs()
    elif command in {"help", "-h", "--help"}:
        help_text()
    else:
        fail(f"unknown command: {command}")


if __name__ == "__main__":
    main()
