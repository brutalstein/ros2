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
import gazebo_runtime as gazebo
import scenarios

ROOT = bootstrap.ROOT
RUNTIME = bootstrap.WORKSPACE / "runtime"
LOGS = RUNTIME / "logs"
LOCK = RUNTIME / "runtime.lock"

AGENT_STATE = RUNTIME / "agent.json"
PX4_STATE = RUNTIME / "px4.json"
CAMERA_BRIDGE_STATE = RUNTIME / "camera-bridge.json"

AGENT_LOG = LOGS / "microxrce-agent.log"
PX4_LOG = LOGS / "px4.log"
CAMERA_BRIDGE_LOG = LOGS / "camera-bridge.log"


def say(message: str = "") -> None:
    print(message, flush=True)


def fail(message: str) -> None:
    raise SystemExit(f"[FAIL] {message}")


def ensure_dirs() -> None:
    bootstrap.ensure_dirs()
    RUNTIME.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)


def manifest() -> dict:
    return bootstrap.load_manifest()


def ensure_ready() -> tuple[dict, dict, dict]:
    m = manifest()
    info = bootstrap.detect_platform()
    missing_ros_packages = [
        package
        for package in m["stack"]["ros"]["apt_packages"]
        if not bootstrap.package_installed(package)
    ]
    verified = bootstrap.verify(m, info, strict=False)
    if not verified or missing_ros_packages:
        say("[INFO] runtime dependencies drifted; repairing the pinned toolchain")
        bootstrap.setup(m)
    return m, bootstrap.detect_platform(), bootstrap.load_state()


def process_start_ticks(pid: int) -> str | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    end = text.rfind(")")
    fields = text[end + 2 :].split() if end >= 0 else []
    return fields[19] if len(fields) > 19 else None


def identity(pid: int, kind: str, **extra) -> dict:
    return {
        "pid": pid,
        "start_ticks": process_start_ticks(pid),
        "kind": kind,
        "owned": True,
        **extra,
    }


def alive(state: dict | None) -> bool:
    if not state:
        return False
    try:
        pid = int(state["pid"])
        os.kill(pid, 0)
    except (KeyError, TypeError, ValueError, OSError):
        return False
    return process_start_ticks(pid) == state.get("start_ticks")


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


def udp_bound(port: int) -> bool:
    wanted = f"{port:04X}"
    for table in (Path("/proc/net/udp"), Path("/proc/net/udp6")):
        try:
            lines = table.read_text(encoding="utf-8").splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) > 1 and ":" in fields[1] and fields[1].rsplit(":", 1)[1].upper() == wanted:
                return True
    return False


def wait_for(predicate, seconds: float, interval: float = 0.1) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


def state_paths(state: dict, m: dict) -> tuple[Path, Path, int]:
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


def start_agent(agent_bin: Path, port: int) -> None:
    tracked = read_state(AGENT_STATE)
    if alive(tracked) and udp_bound(port):
        say(f"[OK] DDS Agent ready | UDP {port}")
        return
    if tracked:
        clear_state(AGENT_STATE)
    if udp_bound(port):
        fail(f"UDP {port} is occupied by an unmanaged process")
    if not agent_bin.is_file():
        fail(f"managed MicroXRCEAgent is missing: {agent_bin}")

    env = os.environ.copy()
    local_lib = str(agent_bin.parent.parent / "lib")
    env["LD_LIBRARY_PATH"] = local_lib + (":" + env["LD_LIBRARY_PATH"] if env.get("LD_LIBRARY_PATH") else "")

    with AGENT_LOG.open("a", encoding="utf-8") as log:
        log.write(f"\n===== {time.strftime('%F %T')} DDS Agent UDP {port} =====\n")
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
        fail("DDS Agent did not become ready; run ./mission logs")
    say(f"[OK] DDS Agent ready | UDP {port}")


def terminal_command(info: dict, linux_command: str) -> list[str] | None:
    if info["wsl2"]:
        cmd = shutil.which("cmd.exe") or "/mnt/c/Windows/System32/cmd.exe"
        if not Path(cmd).exists() and not shutil.which("cmd.exe"):
            return None
        distro = info.get("wsl_distro")
        wsl = ["wsl.exe"]
        if distro:
            wsl += ["-d", distro]
        wsl += ["--", "bash", "-lc", linux_command]
        return [cmd, "/c", "start", "", "wt.exe", "new-tab", "--title", "PX4 SITL", *wsl]

    if shutil.which("gnome-terminal"):
        return ["gnome-terminal", "--", "bash", "-lc", linux_command]
    if shutil.which("konsole"):
        return ["konsole", "-e", "bash", "-lc", linux_command]
    if shutil.which("x-terminal-emulator"):
        return ["x-terminal-emulator", "-e", "bash", "-lc", linux_command]
    return None


def px4_environment() -> dict:
    env = os.environ.copy()
    config = scenarios.load_config()
    selected = scenarios.current_name(config)
    worlds = scenarios.worlds_dir(config)

    env["PX4_GZ_WORLD"] = selected
    env["PX4_GZ_STANDALONE"] = "1"
    env["GZ_PARTITION"] = gazebo.PARTITION
    env["DRONE_RUNTIME_OWNER"] = gazebo.OWNER_ID

    existing = [value for value in env.get("GZ_SIM_RESOURCE_PATH", "").split(":") if value]
    world_path = str(worlds)
    if world_path not in existing:
        existing.insert(0, world_path)
    env["GZ_SIM_RESOURCE_PATH"] = ":".join(existing)
    return env


def launch_px4(info: dict, target: str) -> None:
    tracked = read_state(PX4_STATE)
    if alive(tracked):
        if tracked.get("target") != target:
            fail("PX4 is already running with another vehicle; run ./mission stop")
        say(f"[OK] PX4 ready | target={target}")
        return

    tool = Path(__file__).resolve()
    linux_command = (
        f"cd {shlex.quote(str(ROOT))} && "
        f"exec python3 {shlex.quote(str(tool))} _px4-run {shlex.quote(target)}"
    )
    command = terminal_command(info, linux_command)

    if command is None:
        say("[INFO] no terminal launcher detected; PX4 output will use the mission logs")
        subprocess.Popen(
            [sys.executable, str(tool), "_px4-background", target],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    else:
        result = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            fail("could not open the PX4 terminal: " + result.stderr.strip())

    if not wait_for(lambda: alive(read_state(PX4_STATE)), 15.0, 0.2):
        fail("PX4 did not register within 15 seconds; run ./mission logs")
    say(f"[OK] PX4 ready | target={target}")


def px4_process(target: str | None = None, background: bool = False) -> None:
    m = manifest()
    state = bootstrap.load_state()
    px4_dir, _, _ = state_paths(state, m)
    target = target or m["stack"]["px4"]["sim_target"]
    if not px4_dir.is_dir():
        fail(f"PX4 checkout is missing: {px4_dir}")

    output = None
    if background:
        ensure_dirs()
        output = PX4_LOG.open("a", encoding="utf-8")
        output.write(f"\n===== {time.strftime('%F %T')} PX4 target={target} =====\n")
        output.flush()

    process = subprocess.Popen(
        ["make", "px4_sitl", target],
        cwd=px4_dir,
        env=px4_environment(),
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


def camera_config(m: dict) -> dict:
    return m["stack"]["camera_bridge"]


def gazebo_topics() -> list[str]:
    env = os.environ.copy()
    env["GZ_PARTITION"] = gazebo.PARTITION
    code, out, _ = bootstrap.capture(["gz", "topic", "-l"], env=env)
    if code != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def select_camera_topics(topic_names: list[str], cfg: dict, preferred_model: str = "") -> tuple[str | None, str | None]:
    image_suffix = cfg["gazebo_image_suffix"]
    info_suffix = cfg["gazebo_info_suffix"]
    images = sorted(topic for topic in topic_names if topic.endswith(image_suffix))
    if not images:
        return None, None

    preferred = preferred_model.removeprefix("gz_")
    if preferred:
        preferred_images = [
            topic
            for topic in images
            if f"/model/{preferred}_" in topic or f"/model/{preferred}/" in topic
        ]
        if preferred_images:
            images = preferred_images

    image = images[0]
    prefix = image[: -len(image_suffix)]
    expected_info = prefix + info_suffix
    info = expected_info if expected_info in topic_names else None
    return image, info


def discover_camera_topics(m: dict, target: str, timeout: float | None = None) -> tuple[str | None, str | None]:
    cfg = camera_config(m)
    timeout = float(cfg.get("startup_timeout_seconds", 30) if timeout is None else timeout)
    found: list[str | None] = [None, None]

    def probe() -> bool:
        image, info = select_camera_topics(gazebo_topics(), cfg, preferred_model=target)
        found[0] = image
        found[1] = info
        return image is not None and (info is not None or not cfg.get("bridge_camera_info", True))

    if not wait_for(probe, timeout, 0.5):
        return None, None
    return found[0], found[1]


def ros_package_available(m: dict, package: str) -> bool:
    env = bootstrap.ros_environment(m)
    code, _, _ = bootstrap.capture(["ros2", "pkg", "prefix", package], env=env)
    return code == 0


def ros_topic_type(m: dict, topic: str) -> str:
    env = bootstrap.ros_environment(m)
    try:
        result = subprocess.run(
            ["ros2", "topic", "type", topic],
            env=env,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=3,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def camera_bridge_required(m: dict, target: str) -> bool:
    cfg = camera_config(m)
    return cfg.get("enabled", True) and target in cfg.get("targets", [m["stack"]["px4"]["sim_target"]])


def start_camera_bridge(m: dict, target: str) -> None:
    if not camera_bridge_required(m, target):
        return

    tracked = read_state(CAMERA_BRIDGE_STATE)
    if alive(tracked):
        say("[OK] camera bridge ready")
        return
    if tracked:
        clear_state(CAMERA_BRIDGE_STATE)

    cfg = camera_config(m)
    package = cfg.get("ros_package", "ros_gz_bridge")
    if not ros_package_available(m, package):
        fail(f"ROS package {package!r} is unavailable; run ./dev setup")

    say("[INFO] waiting for the simulated camera")
    image_topic, info_topic = discover_camera_topics(m, target)
    if not image_topic:
        fail("Gazebo camera topic was not discovered; run ./mission logs")

    ros_image = cfg["ros_image_topic"]
    ros_info = cfg["ros_info_topic"]
    bridge_specs = [f"{image_topic}@sensor_msgs/msg/Image[gz.msgs.Image"]
    remaps = ["-r", f"{image_topic}:={ros_image}"]

    if info_topic and cfg.get("bridge_camera_info", True):
        bridge_specs.append(f"{info_topic}@sensor_msgs/msg/CameraInfo[gz.msgs.CameraInfo")
        remaps += ["-r", f"{info_topic}:={ros_info}"]

    env = bootstrap.ros_environment(m)
    command = ["ros2", "run", package, "parameter_bridge", *bridge_specs, "--ros-args", *remaps]
    with CAMERA_BRIDGE_LOG.open("a", encoding="utf-8") as log:
        log.write(f"\n===== {time.strftime('%F %T')} camera bridge =====\n")
        log.write(f"Gazebo image: {image_topic}\nROS image: {ros_image}\n")
        log.flush()
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )

    item = identity(
        process.pid,
        "ros-gz-camera-bridge",
        gazebo_image_topic=image_topic,
        ros_image_topic=ros_image,
    )
    write_state(CAMERA_BRIDGE_STATE, item)
    ready = wait_for(
        lambda: alive(item) and ros_topic_type(m, ros_image) == "sensor_msgs/msg/Image",
        float(cfg.get("bridge_timeout_seconds", 12)),
        0.5,
    )
    if not ready:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except OSError:
            pass
        clear_state(CAMERA_BRIDGE_STATE)
        fail("camera bridge did not become ready; run ./mission logs")
    say(f"[OK] camera ready | {ros_image}")


def terminate(path: Path, label: str) -> None:
    state = read_state(path)
    if not state:
        return
    if not alive(state):
        clear_state(path)
        return

    pid = int(state["pid"])
    for sig, timeout in ((signal.SIGINT, 5.0), (signal.SIGTERM, 3.0)):
        try:
            os.killpg(pid, sig)
        except OSError:
            pass
        if wait_for(lambda: not alive(state), timeout):
            clear_state(path)
            say(f"[OK] stopped {label}")
            return
    say(f"[WARN] {label} did not stop cleanly")


def resolve_target(m: dict, requested: str | None = None) -> str:
    if requested:
        return requested
    return os.environ.get("PX4_SIM_TARGET", m["stack"]["px4"]["sim_target"])


def start(requested_target: str | None = None) -> None:
    ensure_dirs()
    m, info, state = ensure_ready()
    target = resolve_target(m, requested_target)
    _, agent_bin, port = state_paths(state, m)

    with LOCK.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        start_agent(agent_bin, port)
        launch_px4(info, target)
        start_camera_bridge(m, target)

    say("[OK] ROS/PX4 runtime ready")


def stop() -> None:
    ensure_dirs()
    with LOCK.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        terminate(CAMERA_BRIDGE_STATE, "camera bridge")
        terminate(PX4_STATE, "PX4")
        terminate(AGENT_STATE, "DDS Agent")


def status() -> None:
    m = manifest()
    state = bootstrap.load_state()
    _, _, port = state_paths(state, m)
    agent = read_state(AGENT_STATE)
    px4 = read_state(PX4_STATE)
    bridge = read_state(CAMERA_BRIDGE_STATE)

    say(f"DDS Agent : {'RUNNING' if alive(agent) else 'STOPPED'} | UDP {port}")
    say(f"PX4       : {'RUNNING' if alive(px4) else 'STOPPED'}")
    if alive(px4):
        say(f"PX4 target: {px4.get('target', '?')}")
    say(f"Camera    : {'READY' if alive(bridge) else 'STOPPED'}")


def logs() -> None:
    for path in (AGENT_LOG, PX4_LOG, CAMERA_BRIDGE_LOG):
        say(f"\n===== {path.relative_to(ROOT)} =====")
        if not path.exists():
            say("(no log yet)")
            continue
        say("\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]))


def main() -> None:
    # Internal child-process entrypoints. User-facing runtime commands live in ./mission.
    args = sys.argv[1:]
    command = args[0] if args else ""
    if command == "_px4-run":
        px4_process(target=args[1] if len(args) > 1 else None, background=False)
    elif command == "_px4-background":
        px4_process(target=args[1] if len(args) > 1 else None, background=True)
    else:
        fail("runtime.py is internal; use ./mission")


if __name__ == "__main__":
    main()
