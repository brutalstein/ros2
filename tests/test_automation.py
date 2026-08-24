import json
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import bootstrap  # noqa: E402
import dev  # noqa: E402
import qgroundcontrol  # noqa: E402
import runtime  # noqa: E402


class ToolchainContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = bootstrap.load_manifest()

    def test_public_entrypoints_are_small(self):
        for name in ("dev", "mission", "ros"):
            self.assertTrue((ROOT / name).is_file(), name)
        self.assertFalse((ROOT / "drone").exists())
        self.assertFalse((ROOT / "tools" / "drone.py").exists())
        self.assertTrue((ROOT / "tools" / "runtime.py").is_file())

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

    def test_minimal_cpp_application(self):
        registry = (ROOT / "app/runtime/node_registry.hpp").read_text(encoding="utf-8")
        self.assertIn('{"camera", make_camera_node}', registry)
        self.assertIn('{"flight", make_flight_node}', registry)
        self.assertNotIn("make_core_node", registry)
        self.assertNotIn("make_state_node", registry)
        self.assertNotIn("make_sensors_node", registry)

        for removed in ("core", "state", "sensors"):
            self.assertFalse((ROOT / "app" / removed).exists())

        app_cpp = sorted((ROOT / "app").rglob("*.cpp"))
        self.assertEqual(
            sum("int main(" in path.read_text(encoding="utf-8") for path in app_cpp),
            1,
        )

    def test_node_registry_matches_discovery(self):
        discovered = set(dev.module_map())
        registered = set(dev.registry_nodes())
        self.assertEqual(discovered, {"camera", "flight"})
        self.assertEqual(registered, discovered)

        registry = (ROOT / "app/runtime/node_registry.hpp").read_text(encoding="utf-8")
        self.assertIn("DRONE_NODE_INCLUDES", registry)
        self.assertIn("DRONE_NODE_ENTRIES", registry)
        self.assertIn("NodeSpec", registry)

        main = (ROOT / "app/main.cpp").read_text(encoding="utf-8")
        self.assertIn("DRONE_ONLY_NODE", main)
        self.assertIn("make_nodes(only_node)", main)

    def test_dev_discovers_nodes_and_helpers(self):
        camera = ROOT / "app/camera/camera.cpp"
        flight = ROOT / "app/flight/flight.cpp"
        publisher = ROOT / "app/flight/publisher/publisher.cpp"
        self.assertEqual(dev.source_kind(camera), "node")
        self.assertEqual(dev.source_kind(flight), "node")
        self.assertEqual(dev.source_kind(publisher), "helper")
        self.assertEqual(dev.validate_module_contract(camera), [])
        self.assertEqual(dev.validate_module_contract(flight), [])

    def test_dev_command_surface_is_intentionally_small(self):
        source = (ROOT / "tools/dev.py").read_text(encoding="utf-8")
        for command in ("setup", "build", "test", "nodes", "new", "run", "clean"):
            self.assertIn(f'command == "{command}"', source)
        for obsolete in (
            'command == "doctor"',
            'command == "verify"',
            'command == "fmt"',
            'command == "shell"',
            'command == "rebuild"',
        ):
            self.assertNotIn(obsolete, source)

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

    def test_camera_runtime_contract(self):
        stack = self.manifest["stack"]
        camera = stack["camera_bridge"]
        self.assertEqual(stack["px4"]["sim_target"], "gz_x500_mono_cam")
        self.assertEqual(camera["ros_image_topic"], "/camera/image_raw")

        topics = [
            "/world/default/model/other_0/link/camera_link/sensor/imager/image",
            "/world/default/model/x500_mono_cam_12/link/camera_link/sensor/imager/camera_info",
            "/world/default/model/x500_mono_cam_12/link/camera_link/sensor/imager/image",
        ]
        image, info = runtime.select_camera_topics(
            topics,
            camera,
            preferred_model="gz_x500_mono_cam",
        )
        self.assertIn("x500_mono_cam_12", image)
        self.assertTrue(info.endswith("/camera_info"))

    def test_mission_owns_qgc_and_runtime_orchestration(self):
        mission = (ROOT / "tools/mission.py").read_text(encoding="utf-8")
        dev_source = (ROOT / "tools/dev.py").read_text(encoding="utf-8")
        why = (ROOT / "tools/why.py").read_text(encoding="utf-8")

        self.assertIn("qgroundcontrol.setup()", dev_source)
        self.assertIn("qgc.start()", mission)
        self.assertIn("gazebo.start(scenario)", mission)
        self.assertIn("runtime.start()", mission)
        self.assertIn("qgc.wait_connected()", mission)
        self.assertIn("why.report()", mission)
        self.assertIn("import runtime", why)
        self.assertNotIn("PX4_PARAM_NAV_DLL_ACT", mission)
        self.assertEqual(
            qgroundcontrol.binary_path(self.manifest).name,
            self.manifest["stack"]["qgroundcontrol"]["filename"],
        )

    def test_ros_wrapper_is_inspection_focused(self):
        source = (ROOT / "tools/ros.py").read_text(encoding="utf-8")
        for command in ("topics", "nodes", "node", "echo", "once", "rate", "info"):
            self.assertIn(f'command == "{command}"', source)
        for removed in ("send", "call", "services", "params", "set", "doctor"):
            self.assertNotIn(f'command == "{removed}"', source)

    def test_scenario_worlds(self):
        config = json.loads((ROOT / "simulation/scenarios.json").read_text())
        self.assertEqual(config["default"], "training_field")
        worlds = ROOT / config["worlds_dir"]
        for name in config["scenarios"]:
            root = ET.parse(worlds / f"{name}.sdf").getroot()
            self.assertEqual(root.tag, "sdf")
            self.assertEqual(root.get("version"), "1.9")
            self.assertEqual(root.find("world").get("name"), name)

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
