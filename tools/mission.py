#!/usr/bin/env python3
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import bootstrap


ROOT = bootstrap.ROOT
MISSION_CPP = ROOT / "mission.cpp"
RUNTIME_DIR = bootstrap.WORKSPACE / "mission"
PID_FILE = RUNTIME_DIR / "app.pid"
LOG_FILE = RUNTIME_DIR / "app.log"


def say(message: str = "") -> None:
    print(message, flush=True)


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] {message}")


def read_pid() -> int | None:
    if not PID_FILE.exists():
        return None

    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except (ValueError, OSError):
        return None


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def clear_stale_pid() -> None:
    pid = read_pid()
    if pid is not None and process_alive(pid):
        return

    if PID_FILE.exists():
        PID_FILE.unlink()


def build_app() -> None:
    say("[INFO] building mission + application")
    subprocess.run([str(ROOT / "dev"), "b"], cwd=ROOT, check=True)


def start_simulation() -> None:
    say("[INFO] starting Gazebo GUI + PX4 + DDS/ROS bridges")
    subprocess.run([str(ROOT / "drone"), "start"], cwd=ROOT, check=True)


def stop_simulation() -> None:
    say("[INFO] stopping PX4/Gazebo runtime")
    subprocess.run([str(ROOT / "drone"), "cleanup"], cwd=ROOT, check=False)


def stop_app() -> None:
    clear_stale_pid()
    pid = read_pid()

    if pid is None:
        return

    if not process_alive(pid):
        PID_FILE.unlink(missing_ok=True)
        return

    say(f"[INFO] stopping mission app process group {pid}")

    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)
        return

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        if not process_alive(pid):
            break
        time.sleep(0.1)

    if process_alive(pid):
        say("[WARN] mission app did not stop gracefully; killing it")
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    PID_FILE.unlink(missing_ok=True)


def start_app() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)

    manifest = bootstrap.load_manifest()
    env = bootstrap.ros_environment(manifest, include_workspace=True)
    env["DRONE_MISSION_AUTOSTART"] = "1"

    log_handle = LOG_FILE.open("w", encoding="utf-8")

    process = subprocess.Popen(
        ["ros2", "run", "drone", "drone_app"],
        cwd=ROOT,
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        text=True,
    )

    log_handle.close()
    PID_FILE.write_text(f"{process.pid}\n", encoding="utf-8")

    time.sleep(1.0)

    if process.poll() is not None:
        PID_FILE.unlink(missing_ok=True)
        fail(f"mission app exited during startup; inspect {LOG_FILE.relative_to(ROOT)}")

    say(f"[OK] mission app started | pid={process.pid}")
    say(f"[INFO] app log: {LOG_FILE.relative_to(ROOT)}")


def start() -> None:
    if not MISSION_CPP.is_file():
        fail("mission.cpp is missing from repository root")

    clear_stale_pid()
    pid = read_pid()
    if pid is not None and process_alive(pid):
        fail(f"mission is already running | pid={pid}")

    # A failed previous run must not leak PX4/Gazebo processes into this run.
    stop_simulation()

    build_app()

    try:
        start_simulation()
        start_app()
    except BaseException:
        stop_app()
        stop_simulation()
        raise

    say("[OK] mission started")
    say("[INFO] mission.cpp is running through the Drone API")


def stop() -> None:
    stop_app()
    stop_simulation()
    say("[OK] mission stopped; runtime state reset")


def status() -> None:
    clear_stale_pid()
    pid = read_pid()

    if pid is None:
        say("mission app: stopped")
    else:
        say(f"mission app: running | pid={pid}")

    subprocess.run([str(ROOT / "drone"), "status"], cwd=ROOT, check=False)


def logs() -> None:
    if not LOG_FILE.exists():
        fail("mission app log does not exist yet")

    print(LOG_FILE.read_text(encoding="utf-8", errors="replace"), end="")


def help_text() -> None:
    say(
        """Usage:
  ./mission start    build mission.cpp, start Gazebo/PX4, then run the app
  ./mission stop     stop the app and clean the complete simulation runtime
  ./mission status   show app + simulation status
  ./mission logs     print the application log
"""
    )


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else ""

    if command == "start":
        start()
    elif command == "stop":
        stop()
    elif command == "status":
        status()
    elif command == "logs":
        logs()
    else:
        help_text()
        if command:
            raise SystemExit(2)


if __name__ == "__main__":
    main()
