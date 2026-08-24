#!/usr/bin/env python3
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import bootstrap
import drone as runtime
import qgroundcontrol as qgc

ROOT = bootstrap.ROOT
MISSION_LOG = bootstrap.WORKSPACE / "mission" / "app.log"
PX4_LOG = bootstrap.WORKSPACE / "runtime" / "logs" / "px4.log"

STATUS_TOPIC = "/fmu/out/vehicle_status_v1"
POSITION_TOPIC = "/fmu/out/vehicle_local_position_v1"
FAILSAFE_TOPIC = "/fmu/out/failsafe_flags"
ESTIMATOR_TOPIC = "/fmu/out/estimator_status_flags"


def read_topic(topic: str) -> dict[str, str]:
    env = bootstrap.ros_environment(bootstrap.load_manifest(), include_workspace=True)
    command = [
        "ros2", "topic", "echo", topic, "--once",
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
            timeout=3,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {}

    if result.returncode != 0:
        return {}

    values: dict[str, str] = {}
    for line in result.stdout.splitlines():
        match = re.match(r"^([A-Za-z0-9_]+):\s*(.+?)\s*$", line)
        if match:
            values[match.group(1)] = match.group(2)
    return values


def as_bool(value: str | None) -> bool:
    return (value or "").lower() == "true"


def as_int(value: str | None, default: int = -1) -> int:
    try:
        return int(value or "")
    except ValueError:
        return default


def current_log_lines(path: Path) -> list[str]:
    if not path.exists():
        return []

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    # PX4 logs are appended between runs. Only inspect the current/last run so
    # a previous preflight failure cannot become today's diagnosis.
    if path == PX4_LOG:
        markers = [index for index, line in enumerate(lines) if line.startswith("=====")]
        if markers:
            lines = lines[markers[-1] :]

    return lines[-400:]


def latest_log_reason() -> str | None:
    patterns = (
        re.compile(r"Preflight Fail:\s*(.+)", re.IGNORECASE),
        re.compile(r"(?:Arming|Arm) denied[: ]+(.+)", re.IGNORECASE),
        re.compile(r"takeoff failed \|\s*(.+?)(?:\s*\||$)", re.IGNORECASE),
    )

    for path in (MISSION_LOG, PX4_LOG):
        for line in reversed(current_log_lines(path)):
            for pattern in patterns:
                match = pattern.search(line)
                if match:
                    return match.group(1).strip()
    return None


def main() -> None:
    px4 = runtime.read_state(runtime.PX4_STATE)
    px4_running = runtime.alive(px4)
    qgc_running = qgc.alive()

    status = read_topic(STATUS_TOPIC) if px4_running else {}
    position = read_topic(POSITION_TOPIC) if px4_running else {}
    failsafe_flags = read_topic(FAILSAFE_TOPIC) if px4_running else {}
    estimator = read_topic(ESTIMATOR_TOPIC) if px4_running else {}

    if not px4_running:
        print("PX4: STOPPED")
        print(f"QGroundControl: {'RUNNING' if qgc_running else 'STOPPED'}")
        reason = latest_log_reason()
        print("Takeoff: NOT RUNNING")
        if reason:
            print(f"Last issue: {reason}")
        return

    if not status:
        print("PX4: RUNNING")
        print(f"QGroundControl: {'RUNNING' if qgc_running else 'STOPPED'}")
        print("Takeoff: BLOCKED")
        print("Reason: ROS 2 is not receiving PX4 VehicleStatus; check DDS Agent/uXRCE-DDS.")
        return

    armed = as_int(status.get("arming_state")) == 2
    offboard = as_int(status.get("nav_state")) == 14
    preflight = as_bool(status.get("pre_flight_checks_pass"))
    failsafe = as_bool(status.get("failsafe"))
    gcs_lost = as_bool(status.get("gcs_connection_lost"))
    position_valid = as_bool(position.get("xy_valid")) and as_bool(position.get("z_valid"))

    mode = "OFFBOARD" if offboard else f"MODE {status.get('nav_state', '?')}"
    print(f"PX4: RUNNING | {mode} | {'ARMED' if armed else 'DISARMED'}")
    print(
        f"QGroundControl: {'RUNNING' if qgc_running else 'STOPPED'} | "
        f"PX4 link: {'DISCONNECTED' if gcs_lost else 'CONNECTED'}"
    )
    print(f"Preflight: {'READY' if preflight else 'BLOCKED'} | Local position: {'OK' if position_valid else 'INVALID'}")

    reasons: list[str] = []

    if gcs_lost:
        if qgc_running:
            reasons.append("QGroundControl is open but PX4 has no GCS MAVLink connection")
        else:
            reasons.append("QGroundControl is not running")

    if failsafe:
        reasons.append("PX4 failsafe is active")
    if not position_valid:
        reasons.append("local position is not valid")
    if not offboard:
        reasons.append("PX4 is not in OFFBOARD mode")
    if not preflight:
        reasons.append("PX4 preflight checks are not ready")
    if offboard and preflight and not armed:
        reasons.append("PX4 has not armed yet")

    labels = {
        "angular_velocity_invalid": "angular velocity estimate invalid",
        "attitude_invalid": "attitude estimate invalid",
        "local_altitude_invalid": "local altitude invalid",
        "local_position_invalid": "local position estimate invalid",
        "global_position_invalid": "global position estimate invalid",
        "home_position_invalid": "home position unavailable",
        "offboard_control_signal_lost": "offboard heartbeat/setpoint signal lost",
        "battery_unhealthy": "battery unhealthy",
        "fd_esc_arming_failure": "ESC arming failure",
        "fd_motor_failure": "motor failure detected",
    }
    for key, label in labels.items():
        if as_bool(failsafe_flags.get(key)):
            reasons.append(label)

    if estimator and not as_bool(estimator.get("cs_tilt_align")):
        reasons.append("estimator tilt alignment incomplete")
    if estimator and not as_bool(estimator.get("cs_yaw_align")):
        reasons.append("estimator yaw alignment incomplete")

    log_reason = latest_log_reason()
    if log_reason and not preflight:
        stale_gcs_message = "ground control" in log_reason.lower() and not gcs_lost
        if not stale_gcs_message:
            reasons.insert(0, log_reason)

    unique_reasons: list[str] = []
    for reason in reasons:
        if reason not in unique_reasons:
            unique_reasons.append(reason)

    if armed and offboard and position_valid and not failsafe and not gcs_lost:
        print("Takeoff: ACTIVE/READY")
    elif unique_reasons:
        print("Takeoff: BLOCKED")
        print("Reason: " + "; ".join(unique_reasons[:4]))
    else:
        print("Takeoff: WAITING")


if __name__ == "__main__":
    main()
