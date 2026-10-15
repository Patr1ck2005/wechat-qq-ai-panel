"""Public packaging uses bounded synthetic graphics; no account/runtime data."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import struct
import subprocess
import unittest
import zlib

from panel_fixtures import RecycleFixture

ROOT = Path(__file__).resolve().parents[1]
PWSH = shutil.which("pwsh")
REQUIRED = ("README.md", "AGENTS.md", ".gitignore", "LICENSE", "THIRD_PARTY.md",
            "INTEGRATION.md", "WEB_ENTRY.md", "requirements.lock", "start-panel.cmd")
PANEL = True
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="2" height="2"><rect width="2" height="2" fill="#5268ff"/></svg>'


def png():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)) +
            chunk(b"IDAT", zlib.compress(b"\x00\x00\xff\x80\xff")) + chunk(b"IEND", b""))


@unittest.skipUnless(PWSH, "PowerShell 7 is unavailable")
class PublicReleaseTests(unittest.TestCase):
    def setUp(self):
        self.fixture = RecycleFixture(prefix="public-release-")
        self.root = Path(self.fixture.name)
        for name in REQUIRED:
            self.write(name, "Synthetic public text.\n")
        self.write("scripts/prepare-release.ps1", (ROOT / "scripts/prepare-release.ps1").read_text(encoding="utf-8"))
        self.write("docs/assets/product-overview.svg", SVG)
        self.write("docs/assets/interface-preview.png", png())
        self.write("README.md", '![Product](docs/assets/product-overview.svg)\n<img src="docs/assets/interface-preview.png" alt="Synthetic"/>\n')

    def tearDown(self):
        self.fixture.cleanup()

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
        return path

    def run_release(self, check_only=True):
        command = [PWSH, "-NoProfile", "-NonInteractive", "-File", str(self.root / "scripts/prepare-release.ps1")]
        if check_only:
            command.append("-CheckOnly")
        return subprocess.run(command, text=True, encoding="utf-8", capture_output=True, timeout=30)

    def assert_rejected(self, code):
        run = self.run_release()
        self.assertNotEqual(run.returncode, 0, run.stdout)
        self.assertIn(code, run.stderr)

    def test_exact_asset_copy_and_manifest_hashes(self):
        expected = ["docs/assets/product-overview.svg", "docs/assets/interface-preview.png"]
        if PANEL:
            self.write("resources/dsh/no-tools.mjs", "export const synthetic = true;\n")
            self.write("wq_panel/assets/app.svg", SVG)
            self.write("wq_panel/assets/app.png", png())
            image = png()
            self.write("wq_panel/assets/app.ico", struct.pack("<HHH", 0, 1, 1) +
                       struct.pack("<BBBBHHII", 1, 1, 0, 0, 1, 32, len(image), 22) + image)
            expected += ["wq_panel/assets/app.svg", "wq_panel/assets/app.png", "wq_panel/assets/app.ico"]
            expected.append("resources/dsh/no-tools.mjs")
        run = self.run_release(check_only=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        destination, = (self.root / ".local").glob("release-*")
        manifest = json.loads((destination / "release-manifest.json").read_text(encoding="utf-8"))
        indexed = {entry["path"]: entry for entry in manifest["files"]}
        for relative in expected:
            with self.subTest(asset=relative):
                source = (self.root / relative).read_bytes()
                self.assertEqual((destination / relative).read_bytes(), source)
                self.assertEqual(indexed[relative]["sha256"], hashlib.sha256(source).hexdigest())

    def test_unapproved_asset_is_rejected(self):
        self.write("docs/assets/private-screenshot.png", png())
        self.assert_rejected("Unapproved public asset")

    def test_missing_readme_reference_is_rejected(self):
        self.write("README.md", "![Missing](docs/assets/missing.png)\n")
        self.assert_rejected("README image is absent")

    def test_machine_paths_and_credentials_stay_rejected(self):
        examples = ["D:" + "\\Users\\private-user\\message.db",
                    "api_" + "key = '" + "a" * 32 + "'"]
        for value in examples:
            with self.subTest(example=value[:8]):
                self.write("docs/private.md", value)
                self.assert_rejected("public source")

    def test_svg_active_external_and_oversize_assets_are_rejected(self):
        examples = [SVG.replace("<rect", '<script>alert(1)</script><rect'),
                    SVG.replace("<rect", '<use href="https://example.invalid/image.svg#x"/><rect'),
                    SVG.replace("<rect", '<rect onclick="alert(1)"/><rect'),
                    SVG.replace("<rect", '<style>@import "https://example.invalid/x.css";</style><rect'),
                    SVG + " " * (512 * 1024)]
        for content in examples:
            with self.subTest(example=content[:30]):
                self.write("docs/assets/product-overview.svg", content)
                run = self.run_release()
                self.assertNotEqual(run.returncode, 0, run.stdout)

    @unittest.skipUnless(os.name == "nt", "Windows junction and recycling test")
    def test_linked_asset_directory_is_rejected_and_link_recycled(self):
        target_file = self.write("synthetic-target/content.svg", SVG)
        target = target_file.parent
        link = self.root / "docs/assets/linked"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError as error:
            run = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(target)], capture_output=True)
            self.assertEqual(run.returncode, 0, "Synthetic junction creation failed: " + type(error).__name__)
        try:
            self.assert_rejected("Linked source path")
        finally:
            from send2trash.win.modern import send2trash
            send2trash(str(link))
            self.assertFalse(link.exists())
            self.assertEqual(target_file.read_text(encoding="utf-8"), SVG)


if __name__ == "__main__":
    unittest.main()
