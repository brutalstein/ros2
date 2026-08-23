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


class ToolchainContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = bootstrap.load_manifest()

    def test_pinned_stack_contract(self):
        stack = self.manifest["stack"]
        self.assertEqual(stack["ros"]["distro"], "jazzy")
        self.assertEqual(stack["px4"]["ref"], "v1.17.0")
        self.assertEqual(stack["px4_msgs"]["ref"], "release/1.17")
        self.assertEqual(stack["micro_xrce_dds_agent"]["ref"], "v2.4.3")
        self.assertEqual(stack["gazebo"]["expected_major"], 8)

    def test_camera_runtime_contract(self):
        stack = self.manifest["stack"]
        camera = stack["camera_bridge"]
        self.assertEqual(stack["px4"]["sim_target"], "gz_x500_mono_cam")
        self.assertIn("ros-jazzy-ros-gz", stack["ros"]["apt_packages"])
        self.assertEqual(camera["ros_package"], "ros_gz_bridge")
        self.assertEqual(camera["ros_image_topic"], "/camera/image_raw")
        self.assertEqual(camera["ros_info_topic"], "/camera/camera_info")
        self.assertIn("gz_x500_mono_cam", camera["targets"])

    def test_perception_foundation_contract(self):
        packages = set(self.manifest["stack"]["ros"]["apt_packages"])
        expected = {
            "ros-jazzy-sensor-msgs",
            "ros-jazzy-cv-bridge",
            "ros-jazzy-image-transport",
            "ros-jazzy-image-geometry",
            "ros-jazzy-message-filters",
            "ros-jazzy-vision-msgs",
            "ros-jazzy-geometry-msgs",
            "ros-jazzy-nav-msgs",
            "ros-jazzy-tf2-ros",
            "ros-jazzy-tf2-geometry-msgs",
            "ros-jazzy-tf2-eigen",
            "libopencv-dev",
            "libeigen3-dev",
        }
        self.assertTrue(expected.issubset(packages))

    def test_app_declares_camera_dependencies(self):
        package_xml = (ROOT / "app" / "package.xml").read_text(encoding="utf-8")
        self.assertIn("<depend>sensor_msgs</depend>", package_xml)
        self.assertIn("<depend>cv_bridge</depend>", package_xml)
        self.assertIn("<depend>px4_msgs</depend>", package_xml)

    def test_cpp_foundation_is_wired_into_cmake(self):
        cmake = (ROOT / "app" / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("find_package(OpenCV 4 REQUIRED)", cmake)
        self.assertIn("find_package(Eigen3 REQUIRED)", cmake)
        self.assertIn("Eigen3::Eigen", cmake)

    def test_ament_auto_targets_keep_plain_link_signature(self):
        cmake = (ROOT / "app" / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertNotIn('target_link_libraries("${node}" PRIVATE', cmake)
        self.assertNotIn("target_link_libraries(drone_lib PUBLIC", cmake)

    def test_markerless_application_registry_contract(self):
        cmake = (ROOT / "app" / "CMakeLists.txt").read_text(encoding="utf-8")
        dev_text = (ROOT / "tools" / "dev.py").read_text(encoding="utf-8")
        registry = (ROOT / "app" / "runtime" / "node_registry.hpp").read_text(encoding="utf-8")

        self.assertIn('set(DRONE_ENTRYPOINT "${CMAKE_CURRENT_SOURCE_DIR}/main.cpp")', cmake)
        self.assertIn("Only app/main.cpp may define main()", cmake)
        self.assertIn("ament_auto_add_executable(drone_app", cmake)
        self.assertIn("DRONE_REGISTRY_SOURCE", cmake)
        self.assertIn("DRONE_FACTORY_CALLS", cmake)
        self.assertIn("make_${module_name}_node", cmake)
        self.assertIn('runtime/node_registry.hpp', cmake)

        self.assertEqual(dev.MAIN_CPP, ROOT / "app" / "main.cpp")
        self.assertEqual(dev.ENTRY_EXECUTABLE, "drone_app")
        self.assertIn("validate_module_contract", dev_text)
        self.assertIn("make_{node}_node", dev_text)
        self.assertIn("run_app(rest)", dev_text)
        self.assertNotIn("register_module_in_main", dev_text)
        self.assertNotIn("DRONE_NODE_INCLUDES", dev_text)
        self.assertNotIn("DRONE_NODE_FACTORIES", dev_text)

        self.assertIn("namespace drone_runtime", registry)
        self.assertIn("make_nodes()", registry)

        for module in ("core", "state", "sensors", "camera"):
            path = ROOT / "app" / module / f"{module}.cpp"
            self.assertEqual(dev.validate_module_contract(path), [])

    def test_main_and_flight_are_intentionally_left_for_manual_implementation(self):
        self.assertFalse((ROOT / "app" / "main.cpp").exists())
        self.assertFalse((ROOT / "app" / "flight" / "flight.cpp").exists())
        self.assertFalse((ROOT / "app" / "flight" / "flight.hpp").exists())

        topics = (ROOT / "app" / "constants" / "topics.hpp").read_text(encoding="utf-8")
        self.assertNotIn("/fmu/in/offboard_control_mode", topics)
        self.assertNotIn("/fmu/in/trajectory_setpoint", topics)
        self.assertNotIn("/fmu/in/vehicle_command", topics)

    def test_scenario_world_contract(self):
        config_path = ROOT / "simulation" / "scenarios.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(config["default"], "training_field")
        self.assertGreaterEqual(len(config["scenarios"]), 3)
        worlds_dir = ROOT / config["worlds_dir"]

        for name in config["scenarios"]:
            world_path = worlds_dir / f"{name}.sdf"
            self.assertTrue(world_path.is_file(), f"missing scenario world: {name}")
            root = ET.parse(world_path).getroot()
            self.assertEqual(root.tag, "sdf")
            self.assertEqual(root.get("version"), "1.9")
            world = root.find("world")
            self.assertIsNotNone(world)
            self.assertEqual(world.get("name"), name)
            self.assertIsNotNone(world.find("physics"))
            self.assertIsNotNone(world.find("gravity"))
            self.assertIsNotNone(world.find("spherical_coordinates"))
            self.assertIsNotNone(world.find("model[@name='ground_plane']"))

    def test_drone_launcher_exports_repo_world_path(self):
        launcher = (ROOT / "drone").read_text(encoding="utf-8")
        self.assertIn("GZ_SIM_RESOURCE_PATH", launcher)
        self.assertIn("PX4_GZ_WORLD", launcher)
        self.assertIn("tools/scenarios.py", launcher)

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

    def test_supported_wsl2_profile(self):
        info = {
            "os_id": "ubuntu",
            "os_version": "24.04",
            "architecture": "x86_64",
            "wsl": True,
            "wsl2": True,
        }
        self.assertEqual(bootstrap.validate_platform(info, self.manifest), [])

    def test_supported_native_ubuntu_profile(self):
        info = {
            "os_id": "ubuntu",
            "os_version": "24.04",
            "architecture": "x86_64",
            "wsl": False,
            "wsl2": False,
        }
        self.assertEqual(bootstrap.validate_platform(info, self.manifest), [])

    def test_wsl1_is_rejected(self):
        info = {
            "os_id": "ubuntu",
            "os_version": "24.04",
            "architecture": "x86_64",
            "wsl": True,
            "wsl2": False,
        }
        errors = bootstrap.validate_platform(info, self.manifest)
        self.assertTrue(any("WSL1" in item for item in errors))

    def test_wrong_ubuntu_is_rejected(self):
        info = {
            "os_id": "ubuntu",
            "os_version": "22.04",
            "architecture": "x86_64",
            "wsl": True,
            "wsl2": True,
        }
        errors = bootstrap.validate_platform(info, self.manifest)
        self.assertTrue(any("22.04" in item for item in errors))

    def test_workspace_is_repo_relative(self):
        self.assertEqual(bootstrap.WORKSPACE, ROOT / ".workspace")
        self.assertTrue(str(bootstrap.VENDOR).startswith(str(ROOT)))
        self.assertTrue(str(bootstrap.DEPS).startswith(str(ROOT)))

    def test_no_user_specific_paths_in_automation(self):
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
