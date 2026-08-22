#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import platform
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "toolchain.json"
WORKSPACE = ROOT / ".workspace"
VENDOR = WORKSPACE / "vendor"
BUILD = WORKSPACE / "build"
INSTALL = WORKSPACE / "install"
DEPS = WORKSPACE / "deps"
CACHE = WORKSPACE / "cache"
LOG = WORKSPACE / "log"
LOCK = CACHE / "bootstrap.lock"
STATE = CACHE / "bootstrap-state.json"

BASE_APT_PACKAGES = [
    "git",
    "build-essential",
    "cmake",
    "ninja-build",
    "curl",
    "ca-certificates",
    "software-properties-common",
    "python3",
    "python3-pip",
    "python3-venv",
    "pkg-config",
]


def say(message=""):
    print(message, flush=True)


def fail(message, code=1):
    raise SystemExit(f"[FAIL] {message}")


def load_manifest():
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"invalid toolchain manifest: {exc}")
    if data.get("schema_version") != 1:
        fail("unsupported toolchain.json schema_version")
    return data


def read_os_release():
    result = {}
    path = Path("/etc/os-release")
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key] = value.strip().strip('"')
    return result


def command(name):
    return shutil.which(name)


def capture(args, *, cwd=None, env=None):
    result = subprocess.run(
        [str(x) for x in args],
        cwd=cwd or ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def run(args, *, cwd=None, env=None, check=True, quiet=False):
    args = [str(x) for x in args]
    if not quiet:
        say("+ " + " ".join(shlex.quote(x) for x in args))
    return subprocess.run(args, cwd=cwd or ROOT, env=env, check=check)


def ensure_dirs():
    for path in (WORKSPACE, VENDOR, BUILD, INSTALL, DEPS, CACHE, LOG):
        path.mkdir(parents=True, exist_ok=True)


def memory_gib():
    path = Path("/proc/meminfo")
    if not path.exists():
        return None
    match = re.search(r"^MemTotal:\s+(\d+)\s+kB", path.read_text(), re.MULTILINE)
    if not match:
        return None
    return round(int(match.group(1)) / 1024 / 1024, 1)


def gpu_info():
    if command("nvidia-smi"):
        code, out, _ = capture([
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader",
        ])
        if code == 0 and out:
            return {"vendor": "nvidia", "devices": out.splitlines()}
    if command("lspci"):
        code, out, _ = capture(["lspci"])
        if code == 0:
            lines = [x for x in out.splitlines() if re.search(r"VGA|3D controller", x, re.I)]
            if lines:
                return {"vendor": "other", "devices": lines}
    return {"vendor": "none", "devices": []}


def detect_platform():
    osr = read_os_release()
    kernel = platform.release()
    kernel_lower = kernel.lower()
    is_wsl = "microsoft" in kernel_lower or bool(os.environ.get("WSL_INTEROP"))
    is_wsl2 = is_wsl and ("wsl2" in kernel_lower or Path("/mnt/wslg").exists())
    ram = memory_gib()
    cpus = os.cpu_count() or 1
    memory_workers = max(1, int((ram or 8) // 2))
    jobs = max(1, min(cpus, memory_workers, 12))
    return {
        "os_id": osr.get("ID", "unknown").lower(),
        "os_version": osr.get("VERSION_ID", "unknown"),
        "os_pretty": osr.get("PRETTY_NAME", "unknown"),
        "architecture": platform.machine().lower(),
        "kernel": kernel,
        "wsl": is_wsl,
        "wsl2": is_wsl2,
        "wsl_distro": os.environ.get("WSL_DISTRO_NAME", ""),
        "wslg": bool(Path("/mnt/wslg").exists() or os.environ.get("WAYLAND_DISPLAY")),
        "cpu_count": cpus,
        "memory_gib": ram,
        "build_jobs": jobs,
        "gpu": gpu_info(),
        "repo": str(ROOT),
        "home": str(Path.home()),
    }


def validate_platform(info, manifest):
    support = manifest["support"]
    errors = []
    if info["os_id"] != support["os_id"]:
        errors.append(f"OS {info['os_id']} is unsupported; expected {support['os_id']}")
    if info["os_version"] not in support["os_versions"]:
        errors.append(
            f"Ubuntu {info['os_version']} is unsupported; expected one of {support['os_versions']}"
        )
    if info["architecture"] not in support["architectures"]:
        errors.append(
            f"architecture {info['architecture']} is unsupported; expected {support['architectures']}"
        )
    if info["wsl"] and not info["wsl2"]:
        errors.append("WSL1 is unsupported; use WSL2")
    return errors


def package_installed(name):
    code, out, _ = capture(["dpkg-query", "-W", "-f=${Status}", name])
    return code == 0 and out == "install ok installed"


def apt_install_missing(packages):
    missing = [x for x in packages if not package_installed(x)]
    if not missing:
        return False
    say("[INFO] missing apt packages: " + ", ".join(missing))
    run(["sudo", "-v"])
    run(["sudo", "apt-get", "update"])
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    run(["sudo", "apt-get", "install", "-y", *missing], env=env)
    return True


def ensure_ros(manifest):
    ros = manifest["stack"]["ros"]
    distro = ros["distro"]
    setup = Path(f"/opt/ros/{distro}/setup.bash")
    if setup.exists() and all(package_installed(p) for p in ros["apt_packages"]):
        say(f"[OK] ROS 2 {distro} already installed")
        return

    apt_install_missing(BASE_APT_PACKAGES)
    run(["sudo", "add-apt-repository", "-y", "universe"])

    source_version = ros["apt_source_version"]
    asset = f"ros2-apt-source_{source_version}.noble_all.deb"
    url = (
        "https://github.com/ros-infrastructure/ros-apt-source/releases/download/"
        f"{source_version}/{asset}"
    )
    with tempfile.TemporaryDirectory(prefix="drone-ros-") as tmp:
        target = Path(tmp) / asset
        run(["curl", "-fL", "--retry", "3", "-o", target, url])
        run(["sudo", "dpkg", "-i", target])

    run(["sudo", "apt-get", "update"])
    env = os.environ.copy()
    env["DEBIAN_FRONTEND"] = "noninteractive"
    run(["sudo", "apt-get", "install", "-y", *ros["apt_packages"]], env=env)
    apt_install_missing(["python3-colcon-common-extensions", "python3-rosdep"])
    if not setup.exists():
        fail(f"ROS setup was not created: {setup}")
    say(f"[OK] ROS 2 {distro} installed")


def ros_environment(manifest, *, include_workspace=True):
    distro = manifest["stack"]["ros"]["distro"]
    setup = Path(f"/opt/ros/{distro}/setup.bash")
    if not setup.exists():
        fail(f"ROS 2 {distro} is not installed. Run ./dev setup")
    sources = [setup]
    workspace_setup = INSTALL / "setup.bash"
    if include_workspace and workspace_setup.exists():
        sources.append(workspace_setup)
    source_cmd = " && ".join(f"source {shlex.quote(str(x))}" for x in sources)
    result = subprocess.run(
        ["bash", "-lc", f"{source_cmd} && env -0"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    env = os.environ.copy()
    for entry in result.stdout.split(b"\0"):
        if b"=" not in entry:
            continue
        key, value = entry.split(b"=", 1)
        env[key.decode()] = value.decode(errors="replace")
    return env


def ensure_rosdep(manifest):
    env = ros_environment(manifest, include_workspace=False)
    if not command("rosdep"):
        fail("rosdep missing after ROS installation")
    sources = Path("/etc/ros/rosdep/sources.list.d/20-default.list")
    if not sources.exists():
        run(["sudo", "rosdep", "init"], env=env)
    run(["rosdep", "update"], env=env)


def git_value(repo, *args):
    code, out, _ = capture(["git", *args], cwd=repo)
    return out if code == 0 else ""


def normalize_remote(value):
    value = value.strip().removesuffix(".git")
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value.split(":", 1)[1]
    return value


def checkout_matches(path, expected_repo, expected_ref):
    if not (path / ".git").exists():
        return False
    remote = git_value(path, "remote", "get-url", "origin")
    if normalize_remote(remote) != normalize_remote(expected_repo):
        return False
    exact_tag = git_value(path, "describe", "--tags", "--exact-match", "HEAD")
    branch = git_value(path, "branch", "--show-current")
    if expected_ref.startswith("v"):
        return exact_tag == expected_ref
    return branch == expected_ref


def ensure_checkout(path, repo, ref, *, recursive=False):
    ensure_dirs()
    if path.exists():
        if not (path / ".git").exists():
            fail(f"managed path exists but is not a git checkout: {path}")
        remote = git_value(path, "remote", "get-url", "origin")
        if normalize_remote(remote) != normalize_remote(repo):
            fail(f"refusing to overwrite checkout with unexpected remote: {path}")
        dirty = git_value(path, "status", "--porcelain")
        if dirty:
            fail(f"managed checkout has local changes: {path}")
        if checkout_matches(path, repo, ref):
            if recursive:
                run(["git", "submodule", "update", "--init", "--recursive", "--depth", "1"], cwd=path)
            return path
        say(f"[INFO] aligning {path.name} to {ref}")
        run(["git", "fetch", "--depth", "1", "origin", ref], cwd=path)
        if ref.startswith("v"):
            run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=path)
        else:
            run(["git", "checkout", "-B", ref, "FETCH_HEAD"], cwd=path)
        if recursive:
            run(["git", "submodule", "sync", "--recursive"], cwd=path)
            run(["git", "submodule", "update", "--init", "--recursive", "--depth", "1"], cwd=path)
        return path

    args = ["git", "clone", "--depth", "1", "--branch", ref]
    if recursive:
        args += ["--recursive", "--shallow-submodules"]
    args += [repo, str(path)]
    run(args)
    return path


def resolve_px4_checkout(manifest):
    px4 = manifest["stack"]["px4"]
    override = os.environ.get("PX4_AUTOPILOT_DIR")
    candidates = []
    if override:
        candidates.append(Path(override).expanduser().resolve())
    candidates.append((Path.home() / "PX4-Autopilot").resolve())
    for candidate in candidates:
        if checkout_matches(candidate, px4["repo"], px4["ref"]):
            dirty = git_value(candidate, "status", "--porcelain")
            if dirty:
                say(f"[WARN] compatible external PX4 checkout is dirty; using managed clean checkout instead: {candidate}")
                continue
            say(f"[OK] reusing compatible PX4 checkout: {candidate}")
            return candidate
    managed = VENDOR / "px4-autopilot"
    return ensure_checkout(managed, px4["repo"], px4["ref"], recursive=True)


def ensure_px4_toolchain(px4_dir, info):
    essential = [command("make"), command("cmake"), command("ninja"), command("gz")]
    if all(essential):
        say("[OK] PX4 simulation toolchain already present")
        return
    setup_script = px4_dir / "Tools" / "setup" / "ubuntu.sh"
    if not setup_script.exists():
        fail(f"PX4 setup script missing: {setup_script}")
    say("[INFO] installing PX4 simulation dependencies using the pinned PX4 setup script")
    env = os.environ.copy()
    env["PX4_NO_NUTTX"] = "1"
    run(["bash", setup_script, "--no-nuttx"], cwd=px4_dir, env=env)
    if not command("gz"):
        fail("PX4 setup completed but Gazebo command 'gz' is still unavailable")
    if info["wsl"] and not info["wslg"]:
        say("[WARN] WSLg GUI was not detected; Gazebo GUI may not open")


def ensure_px4_smoke_build(px4_dir, jobs):
    marker = px4_dir / "build" / "px4_sitl_default" / "bin" / "px4"
    stamp = CACHE / "px4-build.json"
    head = git_value(px4_dir, "rev-parse", "HEAD")
    expected = {"head": head, "jobs": jobs}
    current = {}
    if stamp.exists():
        try:
            current = json.loads(stamp.read_text())
        except json.JSONDecodeError:
            current = {}
    if marker.exists() and current.get("head") == head:
        say("[OK] PX4 SITL smoke build already verified")
        return
    say("[INFO] verifying PX4 SITL build with detected hardware parallelism")
    result = subprocess.run(
        ["make", "px4_sitl_default", f"-j{jobs}"],
        cwd=px4_dir,
        check=False,
    )
    if result.returncode != 0:
        fail("PX4 SITL smoke build failed after dependency setup")
    if not marker.exists():
        fail("PX4 SITL build returned success but px4 binary is missing")
    stamp.write_text(json.dumps(expected, indent=2) + "\n")
    say("[OK] PX4 SITL smoke build passed")


def ensure_agent(manifest, jobs):
    spec = manifest["stack"]["micro_xrce_dds_agent"]
    source = ensure_checkout(VENDOR / "micro-xrce-dds-agent", spec["repo"], spec["ref"])
    prefix = DEPS / "micro-xrce-dds-agent"
    binary = prefix / "bin" / "MicroXRCEAgent"
    head = git_value(source, "rev-parse", "HEAD")
    stamp = CACHE / "micro-xrce-dds-agent.json"
    current = {}
    if stamp.exists():
        try:
            current = json.loads(stamp.read_text())
        except json.JSONDecodeError:
            current = {}
    if binary.exists() and current == {"ref": spec["ref"], "head": head}:
        say(f"[OK] Micro XRCE-DDS Agent {spec['ref']} already built")
        return binary

    build_dir = BUILD / "micro-xrce-dds-agent"
    build_dir.mkdir(parents=True, exist_ok=True)
    run([
        "cmake", "-S", source, "-B", build_dir,
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DCMAKE_INSTALL_PREFIX={prefix}",
    ])
    run(["cmake", "--build", build_dir, "--parallel", str(jobs)])
    run(["cmake", "--install", build_dir])
    if not binary.exists():
        fail(f"MicroXRCEAgent build succeeded but binary is missing: {binary}")
    stamp.write_text(json.dumps({"ref": spec["ref"], "head": head}, indent=2) + "\n")
    say(f"[OK] Micro XRCE-DDS Agent ready: {binary}")
    return binary


def ensure_px4_msgs(manifest, jobs):
    spec = manifest["stack"]["px4_msgs"]
    source = ensure_checkout(VENDOR / "px4_msgs", spec["repo"], spec["ref"])
    env = ros_environment(manifest, include_workspace=False)
    env["CMAKE_BUILD_PARALLEL_LEVEL"] = str(jobs)
    marker = INSTALL / "px4_msgs" / "share" / "px4_msgs" / "package.sh"
    stamp = CACHE / "px4-msgs.json"
    head = git_value(source, "rev-parse", "HEAD")
    expected = {"ref": spec["ref"], "head": head, "ros": manifest["stack"]["ros"]["distro"]}
    existing = {}
    if stamp.exists():
        try:
            existing = json.loads(stamp.read_text())
        except json.JSONDecodeError:
            existing = {}
    if marker.exists() and existing == expected:
        say(f"[OK] px4_msgs {spec['ref']} already built")
        return
    run([
        "colcon", "--log-base", LOG, "build",
        "--base-paths", source,
        "--build-base", BUILD,
        "--install-base", INSTALL,
        "--packages-select", "px4_msgs",
        "--symlink-install",
        "--event-handlers", "console_direct+",
    ], env=env)
    if not marker.exists():
        fail("px4_msgs build did not produce the expected install marker")
    stamp.write_text(json.dumps(expected, indent=2) + "\n")
    say(f"[OK] px4_msgs ready: {spec['ref']}")


def ensure_vscode(manifest):
    if not command("code"):
        say("[WARN] VS Code CLI 'code' is not available inside this environment")
        say("[WARN] Open this repository with VS Code Remote - WSL, then rerun ./dev setup")
        return
    code, out, _ = capture(["code", "--list-extensions"])
    installed = {x.strip().lower() for x in out.splitlines()} if code == 0 else set()
    for ext in manifest["vscode"]["extensions"]:
        if ext.lower() in installed:
            continue
        run(["code", "--install-extension", ext, "--force"], check=False)
    say("[OK] VS Code extensions checked")


def write_state(info, manifest, px4_dir, agent_binary):
    data = {
        "manifest_profile": manifest["profile"],
        "platform": info,
        "resolved": {
            "ros_distro": manifest["stack"]["ros"]["distro"],
            "px4_ref": manifest["stack"]["px4"]["ref"],
            "px4_dir": str(px4_dir),
            "px4_msgs_ref": manifest["stack"]["px4_msgs"]["ref"],
            "micro_xrce_dds_agent_ref": manifest["stack"]["micro_xrce_dds_agent"]["ref"],
            "micro_xrce_dds_agent_binary": str(agent_binary),
            "dds_port": manifest["stack"]["micro_xrce_dds_agent"]["port"],
        },
        "updated_at": int(time.time()),
    }
    STATE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def version_line(args):
    code, out, err = capture(args)
    text = out or err
    return text.splitlines()[0] if code == 0 and text else "unavailable"


def verify(manifest, info=None, *, strict=True):
    info = info or detect_platform()
    errors = validate_platform(info, manifest)
    ros = manifest["stack"]["ros"]
    px4 = manifest["stack"]["px4"]
    agent = manifest["stack"]["micro_xrce_dds_agent"]
    state = load_state()

    ros_setup = Path(f"/opt/ros/{ros['distro']}/setup.bash")
    if not ros_setup.exists():
        errors.append(f"ROS {ros['distro']} missing")

    px4_dir_text = state.get("resolved", {}).get("px4_dir", "")
    px4_dir = Path(px4_dir_text) if px4_dir_text else None
    if not px4_dir or not checkout_matches(px4_dir, px4["repo"], px4["ref"]):
        errors.append(f"PX4 checkout is not pinned to {px4['ref']}")

    agent_bin_text = state.get("resolved", {}).get("micro_xrce_dds_agent_binary", "")
    agent_bin = Path(agent_bin_text) if agent_bin_text else None
    if not agent_bin or not agent_bin.exists():
        errors.append("managed MicroXRCEAgent binary missing")
    agent_source = VENDOR / "micro-xrce-dds-agent"
    if not checkout_matches(agent_source, agent["repo"], agent["ref"]):
        errors.append(f"Micro-XRCE-DDS-Agent source is not pinned to {agent['ref']}")

    msgs = manifest["stack"]["px4_msgs"]
    if not checkout_matches(VENDOR / "px4_msgs", msgs["repo"], msgs["ref"]):
        errors.append(f"px4_msgs source is not pinned to {msgs['ref']}")
    if not (INSTALL / "px4_msgs" / "share" / "px4_msgs" / "package.sh").exists():
        errors.append("px4_msgs is not built")

    gazebo_major = manifest["stack"]["gazebo"]["expected_major"]
    if command("gz"):
        text = version_line(["gz", "sim", "--version"])
        match = re.search(r"(?:Gazebo\s+Sim\s+)?(\d+)(?:\.\d+)", text)
        if match and int(match.group(1)) != gazebo_major:
            errors.append(f"Gazebo major {match.group(1)} detected; expected {gazebo_major}")
    else:
        errors.append("Gazebo 'gz' command missing")

    if errors:
        for item in errors:
            say(f"[FAIL] {item}")
        if strict:
            raise SystemExit(1)
        return False

    say(f"[OK] platform: {info['os_pretty']} | {'WSL2' if info['wsl2'] else 'native'} | {info['architecture']}")
    say(f"[OK] hardware: {info['cpu_count']} CPU | {info['memory_gib']} GiB RAM | jobs={info['build_jobs']}")
    if info["gpu"]["devices"]:
        for device in info["gpu"]["devices"]:
            say(f"[OK] GPU: {device}")
    else:
        say("[INFO] no GPU CLI detected; GPU is optional for building")
    say(f"[OK] ROS 2: {ros['distro']}")
    say(f"[OK] PX4: {px4['ref']}")
    say(f"[OK] px4_msgs: {manifest['stack']['px4_msgs']['ref']}")
    say(f"[OK] Micro XRCE-DDS Agent: {agent['ref']}")
    say(f"[OK] Gazebo expected major: {gazebo_major}")
    say("[OK] deterministic stack verification passed")
    return True


def setup(manifest):
    ensure_dirs()
    info = detect_platform()
    errors = validate_platform(info, manifest)
    if errors:
        fail("\n".join(errors))

    say(f"[INFO] profile: {manifest['profile']}")
    say(f"[INFO] system: {info['os_pretty']} | {'WSL2' if info['wsl2'] else 'native'} | {info['architecture']}")
    say(f"[INFO] hardware: {info['cpu_count']} CPU | {info['memory_gib']} GiB RAM | jobs={info['build_jobs']}")
    if info["gpu"]["devices"]:
        say("[INFO] GPU: " + " ; ".join(info["gpu"]["devices"]))
    if info["wsl"]:
        say("[INFO] GPU drivers are never installed inside WSL; host Windows owns the GPU driver")

    with LOCK.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        apt_install_missing(BASE_APT_PACKAGES)
        ensure_ros(manifest)
        ensure_rosdep(manifest)
        px4_dir = resolve_px4_checkout(manifest)
        ensure_px4_toolchain(px4_dir, info)
        ensure_px4_smoke_build(px4_dir, info["build_jobs"])
        agent_binary = ensure_agent(manifest, info["build_jobs"])
        ensure_px4_msgs(manifest, info["build_jobs"])
        ensure_vscode(manifest)
        write_state(info, manifest, px4_dir, agent_binary)
        verify(manifest, info)
    say("[OK] workspace bootstrap complete")
    say("Next: ./dev b")


def shell_exports(manifest):
    state = load_state()
    resolved = state.get("resolved", {})
    ros = manifest["stack"]["ros"]["distro"]
    px4_dir = resolved.get("px4_dir") or str(VENDOR / "px4-autopilot")
    agent_binary = resolved.get("micro_xrce_dds_agent_binary") or str(
        DEPS / "micro-xrce-dds-agent" / "bin" / "MicroXRCEAgent"
    )
    port = manifest["stack"]["micro_xrce_dds_agent"]["port"]
    jobs = detect_platform()["build_jobs"]
    lines = [
        f"export ROS_DISTRO={shlex.quote(ros)}",
        f"export PX4_AUTOPILOT_DIR={shlex.quote(px4_dir)}",
        f"export MICRO_XRCE_AGENT_BIN={shlex.quote(agent_binary)}",
        f"export XRCE_DDS_PORT={port}",
        f"export CMAKE_BUILD_PARALLEL_LEVEL={jobs}",
        f"source {shlex.quote(f'/opt/ros/{ros}/setup.bash')}",
    ]
    setup_file = INSTALL / "setup.bash"
    if setup_file.exists():
        lines.append(f"source {shlex.quote(str(setup_file))}")
    print("\n".join(lines))


def doctor(manifest):
    info = detect_platform()
    say(json.dumps(info, indent=2))
    errors = validate_platform(info, manifest)
    if errors:
        for error in errors:
            say(f"[FAIL] {error}")
        raise SystemExit(1)
    say(f"[OK] compatible profile: {manifest['profile']}")
    state = load_state()
    if state:
        say(f"[OK] resolved state: {STATE.relative_to(ROOT)}")
    else:
        say("[INFO] workspace has not been bootstrapped yet")


def main():
    parser = argparse.ArgumentParser(description="Deterministic WSL/Ubuntu robotics toolchain bootstrap")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("setup")
    sub.add_parser("doctor")
    sub.add_parser("verify")
    detect = sub.add_parser("detect")
    detect.add_argument("--json", action="store_true")
    env = sub.add_parser("env")
    env.add_argument("--shell", action="store_true")
    args = parser.parse_args()

    manifest = load_manifest()
    if args.command == "setup":
        setup(manifest)
    elif args.command == "doctor":
        doctor(manifest)
    elif args.command == "verify":
        verify(manifest)
    elif args.command == "detect":
        info = detect_platform()
        if args.json:
            print(json.dumps(info, indent=2))
        else:
            say(info)
    elif args.command == "env":
        if not args.shell:
            fail("env currently requires --shell")
        shell_exports(manifest)


if __name__ == "__main__":
    main()
