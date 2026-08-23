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
CAMERA_BRIDGE_STATE = RUNTIME / "camera-bridge.json"

AGENT_LOG = LOGS / "microxrce-agent.log"
PX4_LOG = LOGS / "px4.log"
CAMERA_BRIDGE_LOG = LOGS / "camera-bridge.log"


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
    missing_ros_packages = [
        package
        for package in m["stack"]["ros"]["apt_packages"]
        if not bootstrap.package_installed(package)
    ]
    verified = bootstrap.verify(m, info, strict=False)
    if not verified or missing_ros_packages:
        if missing_ros_packages:
            say("[INFO] missing ROS runtime packages: " + ", ".join(missing_ros_packages))
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
    agent_bin = Path(resolved.get("micro_xrce_dds_agent_binary", bootstrap.DEPS / "micro-xrce-dds-agent" / "bin" / "MicroXRCEAgent"))
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


def launch_px4(info, target):
    tracked = read_state(PX4_STATE)
    if alive(tracked):
        running_target = tracked.get("target")
        if running_target != target:
            fail(f"PX4 is already running with target {running_target!r}; run ./drone stop before changing vehicle")
        say(f"[OK] PX4 + Gazebo already running (pid {tracked['pid']})")
        return

    linux_command = f"cd {shlex.quote(str(ROOT))} && exec ./drone _px4-run {shlex.quote(target)}"
    cmd = terminal_command(info, linux_command)
    if cmd is None:
        say("[WARN] no terminal launcher detected; PX4 will run in background and log to .workspace/runtime/logs/px4.log")
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "_px4-background", target],
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
    say(f"[OK] PX4 + Gazebo started (pid {state['pid']}, target={target})")


def px4_process(target=None, background=False):
    m = manifest()
    state = bootstrap.load_state()
    px4_dir, _, _ = state_paths(state, m)
    target = target or m["stack"]["px4"]["sim_target"]
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


def camera_config(m):
    return m["stack"]["camera_bridge"]


def gazebo_topics():
    code, out, _ = bootstrap.capture(["gz", "topic", "-l"])
    if code != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


def select_camera_topics(topic_names, cfg, preferred_model=""):
    image_suffix = cfg["gazebo_image_suffix"]
    info_suffix = cfg["gazebo_info_suffix"]
    images = sorted(topic for topic in topic_names if topic.endswith(image_suffix))
    if not images:
        return None, None

    preferred = preferred_model.removeprefix("gz_")
    if preferred:
        preferred_images = [
            topic for topic in images
            if f"/model/{preferred}_" in topic or f"/model/{preferred}/" in topic
        ]
        if preferred_images:
            images = preferred_images

    image = images[0]
    prefix = image[: -len(image_suffix)]
    expected_info = prefix + info_suffix
    info = expected_info if expected_info in topic_names else None
    return image, info


def discover_camera_topics(m, target, timeout=None):
    cfg = camera_config(m)
    timeout = cfg.get("startup_timeout_seconds", 30) if timeout is None else timeout
    found = [None, None]

    def probe():
        image, info = select_camera_topics(gazebo_topics(), cfg, preferred_model=target)
        found[0] = image
        found[1] = info
        return image is not None and (info is not None or not cfg.get("bridge_camera_info", True))

    if not wait_for(probe, timeout, 0.5):
        return None, None
    return found[0], found[1]


def ros_package_available(m, package):
    env = bootstrap.ros_environment(m)
    code, _, _ = bootstrap.capture(["ros2", "pkg", "prefix", package], env=env)
    return code == 0


def ros_topic_type(m, topic):
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


def camera_bridge_required(m, target):
    cfg = camera_config(m)
    return cfg.get("enabled", True) and target in cfg.get("targets", [m["stack"]["px4"]["sim_target"]])


def start_camera_bridge(m, target):
    if not camera_bridge_required(m, target):
        say(f"[INFO] camera bridge disabled for target {target}")
        return

    tracked = read_state(CAMERA_BRIDGE_STATE)
    if alive(tracked):
        say(f"[OK] camera bridge already running (pid {tracked['pid']})")
        return
    if tracked:
        clear_state(CAMERA_BRIDGE_STATE)

    cfg = camera_config(m)
    package = cfg.get("ros_package", "ros_gz_bridge")
    if not ros_package_available(m, package):
        fail(f"ROS package {package!r} is unavailable after setup. Run ./dev setup and inspect the ROS/Gazebo installation.")

    say("[INFO] waiting for Gazebo camera topics")
    image_topic, info_topic = discover_camera_topics(m, target)
    if not image_topic:
        fail("camera target started, but no Gazebo image topic was discovered; inspect `gz topic -l` and ./drone logs")

    ros_image = cfg["ros_image_topic"]
    ros_info = cfg["ros_info_topic"]
    bridge_specs = [f"{image_topic}@sensor_msgs/msg/Image[gz.msgs.Image"]
    remaps = ["-r", f"{image_topic}:={ros_image}"]

    if info_topic and cfg.get("bridge_camera_info", True):
        bridge_specs.append(f"{info_topic}@sensor_msgs/msg/CameraInfo[gz.msgs.CameraInfo")
        remaps += ["-r", f"{info_topic}:={ros_info}"]

    env = bootstrap.ros_environment(m)
    command = ["ros2", "run", package, "parameter_bridge", *bridge_specs, "--ros-args", *remaps]

    with CAMERA_BRIDGE_LOG.open("a") as log:
        log.write(
            f"\n===== {time.strftime('%F %T')} camera bridge =====\n"
            f"Gazebo image: {image_topic}\n"
            f"ROS image: {ros_image}\n"
        )
        if info_topic:
            log.write(f"Gazebo info: {info_topic}\nROS info: {ros_info}\n")
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
        gazebo_info_topic=info_topic,
        ros_image_topic=ros_image,
        ros_info_topic=ros_info if info_topic else None,
    )
    write_state(CAMERA_BRIDGE_STATE, item)

    ready = wait_for(
        lambda: alive(item) and ros_topic_type(m, ros_image) == "sensor_msgs/msg/Image",
        cfg.get("bridge_timeout_seconds", 12),
        0.5,
    )
    if not ready:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except OSError:
            pass
        clear_state(CAMERA_BRIDGE_STATE)
        fail("camera bridge started but ROS image topic did not become ready; inspect ./drone logs")

    say(f"[OK] camera image: {ros_image} [sensor_msgs/msg/Image]")
    if info_topic:
        say(f"[OK] camera info : {ros_info} [sensor_msgs/msg/CameraInfo]")


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


def resolve_target(m, requested=None):
    aliases = {
        "camera": m["stack"]["px4"]["sim_target"],
        "plain": "gz_x500",
        "down": "gz_x500_mono_cam_down",
        "depth": "gz_x500_depth",
    }
    if not requested:
        return os.environ.get("PX4_SIM_TARGET", m["stack"]["px4"]["sim_target"])
    return aliases.get(requested, requested)


def start(requested_target=None):
    ensure_dirs()
    m, info, state = ensure_ready()
    target = resolve_target(m, requested_target)
    _, agent_bin, port = state_paths(state, m)

    with LOCK.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        start_agent(agent_bin, port)
        launch_px4(info, target)
        start_camera_bridge(m, target)

    say("[OK] simulation runtime ready")
    say("Camera: ./ros info /camera/image_raw")
    say("ROS:    ./ros topics")
    say("Nodes:  ./dev r <node>")


def stop():
    ensure_dirs()
    with LOCK.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        terminate(CAMERA_BRIDGE_STATE, "camera bridge")
        terminate(PX4_STATE, "PX4 + Gazebo")
        terminate(AGENT_STATE, "DDS Agent")


def status():
    m = manifest()
    state = bootstrap.load_state()
    _, _, port = state_paths(state, m)
    agent = read_state(AGENT_STATE)
    px4 = read_state(PX4_STATE)
    bridge = read_state(CAMERA_BRIDGE_STATE)

    say(f"DDS Agent   : {'RUNNING' if alive(agent) else 'STOPPED'} | UDP {port} {'BOUND' if udp_bound(port) else 'FREE'}")
    say(f"PX4/Gazebo  : {'RUNNING' if alive(px4) else 'STOPPED'}")
    if alive(px4):
        say(f"PX4 target   : {px4.get('target', '?')}")
    say(f"Camera bridge: {'RUNNING' if alive(bridge) else 'STOPPED'}")
    if alive(bridge):
        say(f"Camera image : {bridge.get('ros_image_topic', '/camera/image_raw')}")
        if bridge.get("ros_info_topic"):
            say(f"Camera info  : {bridge['ros_info_topic']}")


def logs(follow=False):
    paths = [AGENT_LOG, PX4_LOG, CAMERA_BRIDGE_LOG]
    if follow:
        existing = [str(path) for path in paths if path.exists()]
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
    package = camera_config(m).get("ros_package", "ros_gz_bridge")
    if ros_package_available(m, package):
        say(f"[OK] ROS/Gazebo bridge: {package}")
    else:
        say(f"[FAIL] ROS/Gazebo bridge missing: {package}")
    status()


def help_text():
    say('''Usage:
  ./drone start            start camera X500 + PX4 + DDS + camera bridge
  ./drone start camera     same as default
  ./drone start plain      start X500 without camera bridge
  ./drone start down       start down-facing mono camera X500
  ./drone start depth      start depth-camera X500
  ./drone stop             stop processes started by this runtime
  ./drone status           show runtime and camera status
  ./drone logs             show recent runtime logs
  ./drone logs -f          follow runtime logs
  ./drone doctor           platform/toolchain/runtime diagnostics

Advanced override:
  PX4_SIM_TARGET=<target> ./drone start
  ./drone start <raw-px4-target>

Default ROS camera API:
  /camera/image_raw
  /camera/camera_info
''')


def main():
    args = sys.argv[1:]
    cmd = args[0] if args else "help"
    if cmd == "start":
        start(args[1] if len(args) > 1 else None)
    elif cmd == "stop":
        stop()
    elif cmd == "status":
        status()
    elif cmd == "logs":
        logs("-f" in args[1:] or "--follow" in args[1:])
    elif cmd == "doctor":
        doctor()
    elif cmd == "_px4-run":
        px4_process(target=args[1] if len(args) > 1 else None, background=False)
    elif cmd == "_px4-background":
        px4_process(target=args[1] if len(args) > 1 else None, background=True)
    elif cmd in {"help", "-h", "--help"}:
        help_text()
    else:
        fail(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
