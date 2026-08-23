import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import gazebo_runtime  # noqa: E402


class GazeboRuntimeContractTests(unittest.TestCase):
    def test_runtime_uses_isolated_partition(self):
        self.assertTrue(gazebo_runtime.PARTITION.startswith("drone_"))
        self.assertNotIn("/", gazebo_runtime.PARTITION)
        self.assertTrue(gazebo_runtime.OWNER_ID.startswith("drone-"))

    def test_launcher_uses_px4_standalone_mode(self):
        launcher = (ROOT / "drone").read_text(encoding="utf-8")
        self.assertIn('export PX4_GZ_STANDALONE=1', launcher)
        self.assertIn('tools/gazebo_runtime.py', launcher)
        self.assertIn('GZ_PARTITION', launcher)
        self.assertIn('DRONE_RUNTIME_OWNER', launcher)

    def test_world_is_started_by_absolute_repo_path(self):
        source = (ROOT / "tools" / "gazebo_runtime.py").read_text(encoding="utf-8")
        self.assertIn('["gz", "sim", "--force-version", "8", "-r", "-s", str(world)]', source)
        self.assertIn('["gz", "sdf", "-k", str(world)]', source)
        self.assertIn('generated_gz_env', source)

    def test_shutdown_has_owned_hard_fallback(self):
        source = (ROOT / "tools" / "gazebo_runtime.py").read_text(encoding="utf-8")
        self.assertIn('signal.SIGINT', source)
        self.assertIn('signal.SIGTERM', source)
        self.assertIn('signal.SIGKILL', source)
        self.assertIn('cleanup_legacy_px4_gazebo', source)

    def test_default_world_resolves_inside_repository(self):
        world = gazebo_runtime.validate_scenario("training_field")
        self.assertEqual(world, ROOT / "simulation" / "worlds" / "training_field.sdf")


if __name__ == "__main__":
    unittest.main()
