#!/usr/bin/env python3
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import bootstrap
import dev
import gazebo_runtime as gazebo
import qgroundcontrol as qgc
import runtime
import scenarios
import why

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
    try:
        return int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def process_alive(pid: int | None) -> bool:
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def clear_stale_pid() -> None:
    pid = read_pid()
    if not process_alive(pid):
        PID_FILE.unlink(missing_ok=True)


def stop_app() -> None:
    clear_stale_pid()
    pid = read_pid()
    if pid is None:
        return

    say("[INFO] stopping mission application")
    try:
        os.killpg(pid, signal.SIGTERM)
    except ProcessLookupError:
        PID_FILE.unlink(missing_ok=True)
        return

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and process_alive(pid):
        time.sleep(0.1)

    if process_alive(pid):
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    PID_FILE.unlink(missing_ok=True)


def stop_platform() -> None:
    runtime.stop()
    gazebo.stop()
    qgc.terminate()


def start_app() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    env = bootstrap.ros_environment(bootstrap.load_manifest(), include_workspace=True)
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
        fail("mission application exited during startup; run ./mission logs")
    say(f"[OK] mission application ready | pid={process.pid}")


def selected_scenario() -> str:
    config = scenarios.load_config()
    return scenarios.current_name(config)


def start(requested_scenario: str | None = None) -> None:
    if not MISSION_CPP.is_file():
        fail("mission.cpp is missing")

    clear_stale_pid()
    if process_alive(read_pid()):
        fail("mission is already running; use ./mission stop first")

    # Always start from a known clean runtime. The helpers only stop processes
    # they own, so unrelated Gazebo/QGC sessions are not targeted.
    stop_platform()

    if requested_scenario:
        scenarios.select(requested_scenario)

    scenario = selected_scenario()
    say(f"[INFO] scenario: {scenario}")
    say("[INFO] validating and building the C++ application")
    dev.build()

    try:
        qgc.start()
        gazebo.start(scenario)
        runtime.start()
        qgc.wait_connected()
        start_app()
    except BaseException:
        stop_app()
        stop_platform()
        raise

    say("[OK] mission started")
    say("[INFO] mission.cpp is running through the Drone API")


def stop() -> None:
    stop_app()
    stop_platform()
    say("[OK] mission stopped")


def status() -> None:
    clear_stale_pid()
    pid = read_pid()
    say(f"Mission app   : {'RUNNING' if process_alive(pid) else 'STOPPED'}")
    if process_alive(pid):
        say(f"Mission PID   : {pid}")
    scenarios.print_current()
    qgc.status()
    runtime.status()
    gazebo.status()


def logs() -> None:
    say("===== mission application =====")
    if LOG_FILE.exists():
        say("\n".join(LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()[-100:]))
    else:
        say("(no mission log yet)")
    runtime.logs()
    say("\n===== QGroundControl =====")
    qgc.logs()
    gazebo.logs()


def scenario_command(value: str | None) -> None:
    if value is None or value == "list":
        scenarios.list_scenarios()
    elif value == "reset":
        scenarios.reset()
    else:
        scenarios.select(value)


def help_text() -> None:
    say(
        """Usage:
  ./mission start [SCENARIO]   build and start QGC + Gazebo + PX4 + ROS + mission.cpp
  ./mission stop               stop the complete managed runtime
  ./mission status             show one current runtime snapshot
  ./mission why                explain why takeoff is blocked
  ./mission logs               show recent managed runtime logs
  ./mission scenario [NAME]    list/select a simulation scenario (use reset for default)
"""
    )


def main() -> None:
    args = sys.argv[1:]
    command = args[0] if args else "help"
    rest = args[1:]

    if command == "start":
        if len(rest) > 1:
            fail("Usage: ./mission start [SCENARIO]")
        start(rest[0] if rest else None)
    elif command == "stop":
        if rest:
            fail("Usage: ./mission stop")
        stop()
    elif command == "status":
        status()
    elif command == "why":
        why.report()
    elif command == "logs":
        logs()
    elif command == "scenario":
        if len(rest) > 1:
            fail("Usage: ./mission scenario [NAME|reset]")
        scenario_command(rest[0] if rest else None)
    elif command in {"help", "-h", "--help"}:
        help_text()
    else:
        fail(f"unknown command: {command}")


if __name__ == "__main__":
    main()
