"""Offline native identity checks; no GUI, messages or model are opened."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from panel_fixtures import RecycleFixture
from wq_panel import app
from wq_panel.controller import PanelError


ROOT = Path(__file__).resolve().parents[1]


class ApplicationIdentityTests(unittest.TestCase):
    def test_missing_or_corrupt_assets_fail_instead_of_using_python_icon(self):
        with RecycleFixture("icon-") as temporary:
            directory = Path(temporary)
            with self.assertRaisesRegex(PanelError, "APP_ICON_MISSING"):
                app.load_app_icons(directory)
            (directory / "app.ico").write_bytes(b"invalid icon")
            (directory / "app.png").write_bytes(b"invalid image")
            (directory / "app.svg").write_text("invalid vector", encoding="utf-8")
            with self.assertRaisesRegex(PanelError, "APP_ICON_INVALID"):
                app.load_app_icons(directory)

    def test_native_surfaces_share_assets_and_identity_precedes_window_creation(self):
        icon, tray_image, svg = app.load_app_icons()
        self.assertEqual(icon, (ROOT / "wq_panel/assets/app.ico").resolve())
        self.assertEqual(tray_image.size, (256, 256))
        events = []
        window = MagicMock()
        webview = SimpleNamespace(
            create_window=MagicMock(side_effect=lambda *args, **kwargs: events.append("window") or window),
            start=MagicMock(),
        )
        pystray = SimpleNamespace(Icon=MagicMock(), Menu=MagicMock(), MenuItem=MagicMock())
        store = MagicMock(root=Path("synthetic-storage"))
        with patch.dict(sys.modules, {"webview": webview, "pystray": pystray}), \
                patch.object(app, "SingleInstance"), patch.object(app, "Store", return_value=store), \
                patch.object(app, "Controller"), patch.object(app, "AccessClient"), \
                patch.object(app, "set_application_identity", side_effect=lambda: events.append("identity")):
            app.run()
        self.assertEqual(events, ["identity", "window"])
        self.assertEqual(webview.start.call_args.kwargs["icon"], str(icon))
        supplied_tray = pystray.Icon.call_args.args[1]
        self.assertEqual(supplied_tray.tobytes(), tray_image.tobytes())
        self.assertIn(svg, webview.create_window.call_args.kwargs["html"])
        self.assertNotIn("<!--APP_ICON-->", webview.create_window.call_args.kwargs["html"])

    @unittest.skipUnless(os.name == "nt" and shutil.which("pwsh"), "Windows PowerShell 7 required")
    def test_shortcut_update_preserves_config_and_writes_native_identity_without_launch(self):
        import pythoncom
        from win32com.client import Dispatch
        from win32com.propsys import propsys, pscon
        from win32com.shell import shellcon

        with RecycleFixture("shortcut-") as temporary:
            directory = Path(temporary)
            scripts = directory / "scripts"
            scripts.mkdir()
            shutil.copyfile(ROOT / "scripts/update-shortcut.ps1", scripts / "update-shortcut.ps1")
            assets = directory / "wq_panel/assets"
            assets.mkdir(parents=True)
            for name in ("app.ico", "app.png", "app.svg"):
                shutil.copyfile(ROOT / "wq_panel/assets" / name, assets / name)
            runtime = directory / ".venv"
            subprocess.run([sys.executable, "-m", "venv", "--without-pip", "--system-site-packages", str(runtime)],
                           capture_output=True, text=True, check=True)
            # Reuse the already-installed test dependencies, including pywin32's .pth setup.
            (runtime / "Lib/site-packages/current-runtime.pth").write_text(
                "import site; site.addsitedir(" + repr(sysconfig.get_path("purelib")) + ")\n", encoding="utf-8")
            access_root = directory / "synthetic access"
            (access_root / "scripts").mkdir(parents=True)
            (access_root / "scripts/access.py").write_text("# Synthetic; never executed.\n", encoding="utf-8")
            config = access_root / "selected deployment.json"
            config.write_text(json.dumps({"schemaVersion": 1, "projectRoot": str(access_root),
                                          "pythonExe": sys.executable}), encoding="utf-8")
            link_path = directory / "Synthetic panel.lnk"
            pythoncom.CoInitialize()
            try:
                shell = Dispatch("WScript.Shell")
                link = shell.CreateShortcut(str(link_path))
                link.TargetPath = str(runtime / "Scripts/pythonw.exe")
                link.Arguments = '-m wq_panel --access-config "' + str(config) + '"'
                link.Save()
                environment = os.environ.copy()
                environment["MESSAGING_ACCESS_CONFIG"] = str(directory / "wrong deployment.json")
                for _ in range(2):
                    result = subprocess.run([shutil.which("pwsh"), "-NoProfile", "-File", str(scripts / "update-shortcut.ps1"),
                                             "-ShortcutPath", str(link_path)],
                                            capture_output=True, text=True, env=environment)
                    self.assertEqual(result.returncode, 0, result.stderr)
                updated = shell.CreateShortcut(str(link_path))
                self.assertEqual(updated.Arguments, '-m wq_panel --access-config "' + str(config.resolve()) + '"')
                self.assertEqual(updated.IconLocation, str(assets / "app.ico") + ",0")
                properties = propsys.SHGetPropertyStoreFromParsingName(str(link_path), None,
                    shellcon.GPS_DEFAULT, propsys.IID_IPropertyStore)
                self.assertEqual(properties.GetValue(pscon.PKEY_AppUserModel_ID).GetValue(), app.APP_USER_MODEL_ID)
            finally:
                pythoncom.CoUninitialize()


if __name__ == "__main__":
    unittest.main()
