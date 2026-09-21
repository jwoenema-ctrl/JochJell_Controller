"""Documentation and packaging contract for the Roco 10814 Windows release."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class WlanReleaseContractTests(unittest.TestCase):
    def test_wlan_guide_covers_safe_explicit_setup_without_credentials(self) -> None:
        guide = (ROOT / "docs" / "WLAN_10814.md").read_text(encoding="utf-8")

        for required in (
            "Unlock the z21start once",
            "yellow LAN sockets",
            "router label",
            "Use Roco 10814 WLAN",
            "Save the settings",
            "Connect via WLAN",
            "UDP",
            "21105",
            "https://www.z21.eu/",
        ):
            self.assertIn(required, guide)

        self.assertIn("does not need, request, transmit, or store them", guide)
        self.assertIsNone(
            re.search(r"(?im)^\s*(?:wifi|wi-fi|wlan)?\s*password\s*[:=]\s*\S+", guide),
            "Documentation must never contain a WLAN password value",
        )

    def test_user_facing_docs_link_to_the_10814_guide(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        native = (ROOT / "docs" / "WINDOWS_NATIVE.txt").read_text(encoding="utf-8")

        self.assertIn("docs/WLAN_10814.md", readme)
        self.assertIn("docs/WLAN_10814.md", native)
        self.assertIn("never asks for or stores the WLAN password", readme)
        self.assertIn("never asks for or stores the WLAN password", native)

    def test_native_build_is_one_file_windowed_and_brandable(self) -> None:
        build = (ROOT / "scripts" / "build_native_windows.ps1").read_text(encoding="utf-8")

        self.assertIn("--onefile", build)
        self.assertIn("--windowed", build)
        self.assertIn("--name JochJell-Controller-Native", build)
        self.assertIn("--version-file 'scripts/version_info.txt'", build)
        self.assertIn("frontend/assets/logo.ico", build)

    def test_tagged_workflow_publishes_tested_native_release_assets(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "windows-app.yml").read_text(encoding="utf-8")

        for required in (
            "tags:",
            "- 'v*'",
            "release:",
            "needs: windows",
            "contents: write",
            "gh release create",
            '--repo "$GITHUB_REPOSITORY"',
            "JochJell-Controller-Native.exe",
            "JochJell-Controller-Native-Windows-x64.zip",
            "SHA256SUMS.txt",
            "docs/WLAN_10814.md",
        ):
            self.assertIn(required, workflow)

        self.assertNotIn("--clobber", workflow)
        self.assertLess(
            workflow.index("Test embedded app window"),
            workflow.index("release:"),
            "The release job must remain downstream of executable smoke testing",
        )


if __name__ == "__main__":
    unittest.main()
