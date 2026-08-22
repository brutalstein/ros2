import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import bootstrap  # noqa: E402


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
