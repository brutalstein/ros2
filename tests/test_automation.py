import json
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import bootstrap  # noqa: E402
import dev  # noqa: E402
import drone  # noqa: E402
import qgroundcontrol  # noqa: E402


class ToolchainContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = bootstrap.load_manifest()

    def test_pinned_stack(self):
        stack = self.manifest["stack"]
        self.assertEqual(stack["ros"]["distro"], "jazzy")
        self.assertEqual(stack["px4"]["ref"], "v1.17.0")
        self.assertEqual(stack["px4_msgs"]["ref"], "release/1.17")
        self.assertEqual(stack["micro_xrce_dds_agent"]["ref"], "v2.4.3")
        self.assertEqual(stack["gazebo"]["expected_major"], 8)
        self.assertEqual(stack["qgroundcontrol"]["version"], "v5.0.8")
        self.assertEqual(stack["qgroundcontrol"]["udp_port"], 14550)
        self.assertEqual(
            stack["qgroundcontrol"]["sha256"],
            "06969c67ef58ea063def0a8271447a1cc385438c4a7df36813315b4475146737",
        )
        self.assertEqual(stack["qgroundcontrol"]["size_bytes"], 180816376)

    def test_minimal_cpp_application(self):
        registry = (ROOT / "app/runtime/node_registry.hpp").read_text(encoding="utf-8")
        self.assertIn("make_camera_node()", registry)
        self.assertIn("make_flight_node()", registry)
        self.assertNotIn("make_core_node()", registry)
        self.assertNotIn("make_state_node()", registry)
        self.assertNotIn("make_sensors_node()", registry)

        for removed in ("core", "state", "sensors"):
            self.assertFalse((ROOT / "app" / removed).exists())

        cpp_files = sorted(ROOT.glob("**/*.cpp"))
        app_cpp = [path for path in cpp_files if "app" in path.parts]
        self.assertTrue(app_cpp)
        self.assertEqual(
            sum("int main(" in path.read_text(encoding="utf-8") for path in app_cpp),
            1,
        )

    def test_only_takeoff_and_camera_dependencies(self):
        package_xml = (ROOT / "app/package.xml").read_text(encoding="utf-8")
        for dependency in ("rclcpp", "sensor_msgs", "cv_bridge", "px4_msgs"):
            self.assertIn(f"<depend>{dependency}</depend>", package_xml)
        self.assertNotIn("std_msgs", package_xml)

    def test_cmake_build_contract(self):
        cmake = (ROOT / "app/CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn('set(DRONE_ENTRYPOINT "${CMAKE_CURRENT_SOURCE_DIR}/main.cpp")', cmake)
        self.assertIn("Only app/main.cpp may define main()", cmake)
        self.assertIn("file(GLOB_RECURSE DRONE_CPP", cmake)
        self.assertIn("ament_auto_add_library(drone_lib", cmake)
        self.assertIn("ament_auto_add_executable(drone_app", cmake)
        self.assertIn("find_package(OpenCV 4 REQUIRED)", cmake)
        self.assertNotIn("Eigen3", cmake)

    def test_dev_discovers_nodes_and_helpers(self):
        camera = ROOT / "app/camera/camera.cpp"
        flight = ROOT / "app/flight/flight.cpp"
        publisher = ROOT / "app/flight/publisher/publisher.cpp"

        self.assertEqual(dev.source_kind(camera), "node")
        self.assertEqual(dev.source_kind(flight), "node")
        self.assertEqual(dev.source_kind(publisher), "helper")
        self.assertEqual(dev.validate_module_contract(camera), [])
        self.assertEqual(dev.validate_module_contract(flight), [])

    def test_camera_runtime_contract(self):
        stack = self.manifest["stack"]
        camera = stack["camera_bridge"]
        self.assertEqual(stack["px4"]["sim_target"], "gz_x500_mono_cam")
        self.assertEqual(camera["ros_image_topic"], "/camera/image_raw")
        self.assertIn("gz_x500_mono_cam", camera["targets"])

    def test_camera_topic_discovery_is_instance_agnostic(self):
        camera = self.manifest["stack"]["camera_bridge"]
        topics = [
            "/world/default/model/other_0/link/camera_link/sensor/imager/image",
            "/world/default/model/x500_mono_cam_12/link/camera_link/sensor/imager/camera_info",
            "/world/default/model/x500_mono_cam_12/link/camera_link/sensor/imager/image",
        ]
        image, info = drone.select_camera_topics(
            topics,
            camera,
            preferred_model="gz_x500_mono_cam",
        )
        self.assertIn("x500_mono_cam_12", image)
        self.assertTrue(info.endswith("/camera_info"))

    def test_qgroundcontrol_automation_contract(self):
        qgc = self.manifest["stack"]["qgroundcontrol"]
        launcher = (ROOT / "drone").read_text(encoding="utf-8")
        dev_launcher = (ROOT / "dev").read_text(encoding="utf-8")
        why = (ROOT / "tools/why.py").read_text(encoding="utf-8")
        qgc_tool = (ROOT / "tools/qgroundcontrol.py").read_text(encoding="utf-8")

        self.assertTrue(qgc["enabled"])
        self.assertTrue(qgc["download_url"].startswith("https://github.com/mavlink/QGroundControl/releases/"))
        self.assertEqual(qgroundcontrol.binary_path(self.manifest).name, qgc["filename"])
        self.assertIn("sha256_file", qgc_tool)
        self.assertIn("size_bytes", qgc_tool)

        self.assertIn("tools/qgroundcontrol.py", dev_launcher)
        self.assertIn('python3 "${QGC_TOOL}" start', launcher)
        self.assertIn('python3 "${QGC_TOOL}" wait-connected', launcher)
        self.assertIn('python3 "${QGC_TOOL}" stop', launcher)
        self.assertNotIn("PX4_PARAM_NAV_DLL_ACT", launcher)

        self.assertIn("QGroundControl is not running", why)
        self.assertNotIn("ignored by this SITL profile", why)

    def test_scenario_worlds(self):
        config = json.loads((ROOT / "simulation/scenarios.json").read_text())
        self.assertEqual(config["default"], "training_field")
        worlds = ROOT / config["worlds_dir"]

        for name in config["scenarios"]:
            root = ET.parse(worlds / f"{name}.sdf").getroot()
            self.assertEqual(root.tag, "sdf")
            self.assertEqual(root.get("version"), "1.9")
            self.assertIsNotNone(root.find("world"))

    def test_supported_platforms(self):
        base = {
            "os_id": "ubuntu",
            "os_version": "24.04",
            "architecture": "x86_64",
        }
        self.assertEqual(
            bootstrap.validate_platform({**base, "wsl": True, "wsl2": True}, self.manifest),
            [],
        )
        self.assertEqual(
            bootstrap.validate_platform({**base, "wsl": False, "wsl2": False}, self.manifest),
            [],
        )

    def test_workspace_is_repo_relative(self):
        self.assertEqual(bootstrap.WORKSPACE, ROOT / ".workspace")
        self.assertTrue(str(bootstrap.VENDOR).startswith(str(ROOT)))
        self.assertTrue(str(bootstrap.DEPS).startswith(str(ROOT)))

    def test_no_user_specific_paths(self):
        forbidden = ["/home/spacey", "/home/cenker", "C:\\Users\\"]
        for path in (ROOT / "tools").glob("*.py"):
            text = path.read_text(encoding="utf-8")
            for value in forbidden:
                self.assertNotIn(value, text, f"{value!r} leaked into {path}")

    def test_manifest_is_valid_json(self):
        parsed = json.loads((ROOT / "toolchain.json").read_text())
        self.assertEqual(parsed["schema_version"], 1)


if __name__ == "__main__":
    unittest.main()
