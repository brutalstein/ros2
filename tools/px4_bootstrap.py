#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import workspace_layout as layout

ROOT = layout.ROOT
APP = ROOT / "app"
VENDOR_ROOT = layout.VENDOR_DIR
PX4_MSGS_DIR = VENDOR_ROOT / "px4_msgs"
CACHE_DIR = layout.CACHE_DIR
STAMP_FILE = CACHE_DIR / "px4_msgs.json"
PX4_AUTOPILOT_DIR = Path(
    os.environ.get("PX4_AUTOPILOT_DIR", str(Path.home() / "PX4-Autopilot"))
).expanduser()
PX4_MSGS_REPO = "https://github.com/PX4/px4_msgs.git"
ROS_DISTRO = os.environ.get("ROS_DISTRO", "jazzy")


def say(message=""):
    print(message)


def die(message):
    raise SystemExit(f"[FAIL] {message}")


def run(command, *, cwd=ROOT, capture=False, check=True):
    kwargs = {"cwd": cwd, "check": check, "text": True}
    if capture:
        kwargs.update(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    else:
        say("+ " + " ".join(map(str, command)))
    return subprocess.run(command, **kwargs)


def command_exists(name):
    return shutil.which(name) is not None


def git_output(*args, cwd):
    result = run(["git", *args], cwd=cwd, capture=True, check=False)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def app_uses_px4_msgs():
    if not APP.exists():
        return False

    package_xml = APP / "package.xml"
    if package_xml.exists() and "px4_msgs" in package_xml.read_text(
        encoding="utf-8", errors="ignore"
    ):
        return True

    for path in APP.rglob("*"):
        if not path.is_file() or path.suffix not in {".cpp", ".cc", ".cxx", ".hpp", ".h"}:
            continue
        if "px4_msgs/" in path.read_text(encoding="utf-8", errors="ignore"):
            return True

    return False


def px4_checkout_exists():
    return (
        PX4_AUTOPILOT_DIR.is_dir()
        and (PX4_AUTOPILOT_DIR / ".git").exists()
        and (PX4_AUTOPILOT_DIR / "msg").is_dir()
    )


def detect_px4_msgs_ref():
    override = os.environ.get("PX4_MSGS_REF")
    if override:
        return override, "PX4_MSGS_REF"

    if not px4_checkout_exists():
        return None, None

    # px4_msgs is versioned by PX4 release line. For example PX4 v1.17.x
    # should use px4_msgs release/1.17 rather than assuming an identical tag.
    exact_tag = git_output("describe", "--tags", "--exact-match", "HEAD", cwd=PX4_AUTOPILOT_DIR)
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.\d+(?:[-+].*)?", exact_tag)
    if match:
        return f"release/{match.group(1)}.{match.group(2)}", f"PX4 {exact_tag}"

    description = git_output("describe", "--tags", "--always", "HEAD", cwd=PX4_AUTOPILOT_DIR)
    match = re.search(r"v?(\d+)\.(\d+)", description)
    if match:
        return f"release/{match.group(1)}.{match.group(2)}", "PX4 release line"

    return None, None


def normalize_remote(url):
    value = url.strip().removesuffix(".git")
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value.split(":", 1)[1]
    return value


def current_vendor_identity():
    if not (PX4_MSGS_DIR / ".git").exists():
        return None

    return {
        "head": git_output("rev-parse", "HEAD", cwd=PX4_MSGS_DIR),
        "tag": git_output("describe", "--tags", "--exact-match", "HEAD", cwd=PX4_MSGS_DIR),
        "branch": git_output("branch", "--show-current", cwd=PX4_MSGS_DIR),
        "remote": git_output("remote", "get-url", "origin", cwd=PX4_MSGS_DIR),
        "dirty": bool(git_output("status", "--porcelain", cwd=PX4_MSGS_DIR)),
    }


def vendor_matches_ref(identity, expected_ref):
    if identity is None:
        return False
    if expected_ref.startswith("v"):
        return identity["tag"] == expected_ref
    return identity["branch"] == expected_ref


def ensure_vendor(expected_ref):
    layout.ensure()

    if not command_exists("git"):
        die("git is required for PX4 interface setup")

    if not PX4_MSGS_DIR.exists():
        VENDOR_ROOT.mkdir(parents=True, exist_ok=True)
        run([
            "git", "clone",
            "--depth", "1",
            "--branch", expected_ref,
            PX4_MSGS_REPO,
            str(PX4_MSGS_DIR),
        ])
        say(f"[OK] px4_msgs fetched: {expected_ref}")
        return

    identity = current_vendor_identity()
    if identity is None:
        die(
            f"{PX4_MSGS_DIR.relative_to(ROOT)} exists but is not a git checkout. "
            "Automation will not overwrite it."
        )

    if normalize_remote(identity["remote"]) != normalize_remote(PX4_MSGS_REPO):
        die(
            f"{PX4_MSGS_DIR.relative_to(ROOT)} points to an unexpected remote. "
            "Automation will not overwrite an unknown repository."
        )

    if identity["dirty"]:
        die(
            f"{PX4_MSGS_DIR.relative_to(ROOT)} has local changes. "
            "Automation refuses to modify a dirty interface checkout."
        )

    if vendor_matches_ref(identity, expected_ref):
        return

    say(f"[INFO] aligning px4_msgs to {expected_ref}")
    run(["git", "fetch", "--depth", "1", "origin", expected_ref], cwd=PX4_MSGS_DIR)

    if expected_ref.startswith("v"):
        run(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=PX4_MSGS_DIR)
    else:
        run(["git", "checkout", "-B", expected_ref, "FETCH_HEAD"], cwd=PX4_MSGS_DIR)

    identity = current_vendor_identity()
    if not vendor_matches_ref(identity, expected_ref):
        die(f"px4_msgs checkout could not be aligned to {expected_ref}")


def load_stamp():
    if not STAMP_FILE.exists():
        return {}
    try:
        return json.loads(STAMP_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def install_marker():
    return layout.INSTALL_DIR / "px4_msgs" / "share" / "px4_msgs" / "package.sh"


def build_needed(expected_ref, force=False):
    if force or not install_marker().exists():
        return True

    identity = current_vendor_identity()
    if identity is None:
        return True

    expected = {
        "ros_distro": ROS_DISTRO,
        "ref": expected_ref,
        "head": identity["head"],
    }
    return load_stamp() != expected


def write_stamp(expected_ref):
    identity = current_vendor_identity()
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    STAMP_FILE.write_text(
        json.dumps(
            {
                "ros_distro": ROS_DISTRO,
                "ref": expected_ref,
                "head": identity["head"] if identity else "",
            },
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


def build_px4_msgs(expected_ref, force=False):
    layout.ensure()

    if not command_exists("colcon"):
        die("colcon is required. Run ./dev setup first")

    if not build_needed(expected_ref, force=force):
        say(f"[OK] px4_msgs ready: {expected_ref}")
        return

    if command_exists("rosdep"):
        rosdep_sources = Path("/etc/ros/rosdep/sources.list.d/20-default.list")
        if rosdep_sources.exists():
            run([
                "rosdep", "install",
                "--from-paths", str(PX4_MSGS_DIR),
                "--ignore-src",
                "-r",
                "-y",
            ])

    run([
        "colcon",
        "--log-base", str(layout.LOG_DIR),
        "build",
        "--base-paths", str(PX4_MSGS_DIR),
        "--build-base", str(layout.BUILD_DIR),
        "--install-base", str(layout.INSTALL_DIR),
        "--packages-select", "px4_msgs",
        "--symlink-install",
        "--event-handlers", "console_direct+",
    ])

    if not install_marker().exists():
        die("px4_msgs build completed but its install marker is missing")

    write_stamp(expected_ref)
    say(f"[OK] px4_msgs built: {expected_ref}")


def print_status(expected_ref=None, source=None):
    identity = current_vendor_identity()
    say(f"ROS_DISTRO={ROS_DISTRO}")
    say(f"PX4_AUTOPILOT_DIR={PX4_AUTOPILOT_DIR}")

    if px4_checkout_exists():
        px4_desc = git_output("describe", "--tags", "--always", "HEAD", cwd=PX4_AUTOPILOT_DIR)
        say(f"[OK] PX4 checkout: {px4_desc or 'detected'}")
    else:
        say("[--] PX4 checkout not detected")

    if expected_ref:
        say(f"[OK] expected px4_msgs: {expected_ref} ({source})")
    else:
        say("[--] expected px4_msgs ref unresolved")

    if identity:
        label = identity["tag"] or identity["branch"] or identity["head"][:12]
        say(f"[OK] {PX4_MSGS_DIR.relative_to(ROOT)}: {label}")
    else:
        say(f"[--] {PX4_MSGS_DIR.relative_to(ROOT)} not present")

    say(f"[{'OK' if install_marker().exists() else '--'}] px4_msgs installed in managed workspace")


def ensure(*, auto=False, force=False):
    expected_ref, source = detect_px4_msgs_ref()
    required = app_uses_px4_msgs()

    if expected_ref is None:
        if required:
            die(
                "PX4 code uses px4_msgs but PX4-Autopilot was not detected. "
                "Set PX4_AUTOPILOT_DIR or PX4_MSGS_REF."
            )
        if auto:
            say("[INFO] PX4 checkout not detected; PX4 interface bootstrap skipped")
            return None, None
        die(
            "PX4-Autopilot was not detected. Expected ~/PX4-Autopilot or set "
            "PX4_AUTOPILOT_DIR."
        )

    ensure_vendor(expected_ref)
    build_px4_msgs(expected_ref, force=force)
    return expected_ref, source


def main():
    parser = argparse.ArgumentParser(description="Safe PX4 ROS 2 interface bootstrap")
    parser.add_argument("--auto", action="store_true", help="skip safely when PX4 is not used/detected")
    parser.add_argument("--force", action="store_true", help="force px4_msgs rebuild")
    parser.add_argument("--status", action="store_true", help="show detected versions and paths")
    args = parser.parse_args()

    try:
        expected_ref, source = detect_px4_msgs_ref()
        if args.status:
            print_status(expected_ref, source)
            return

        expected_ref, source = ensure(auto=args.auto, force=args.force)
        if expected_ref:
            print_status(expected_ref, source)
    except subprocess.CalledProcessError as exc:
        die(f"command failed with exit code {exc.returncode}")


if __name__ == "__main__":
    main()
