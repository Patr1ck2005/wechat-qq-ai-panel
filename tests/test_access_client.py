import json
from pathlib import Path
from panel_fixtures import RecycleFixture
import unittest
from unittest.mock import patch

from wq_panel.access import AccessClient, AccessError


class AccessClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = RecycleFixture()
        self.root = Path(self.temp.name)
        self.python = self.root / "python.exe"
        self.python.write_bytes(b"synthetic")
        self.config = self.root / "deployment.json"
        self.config.write_text(json.dumps({"pythonExe": str(self.python), "projectRoot": str(self.root)}), encoding="utf-8")
        self.reader = AccessClient(self.config)

    def tearDown(self):
        self.temp.cleanup()

    def test_json_boundary_is_utf8_and_no_shell(self):
        class Response:
            returncode = 0
            stdout = '{"ok":true,"data":{"conversations":[]}}'
        with patch("wq_panel.access.subprocess.run", return_value=Response()) as run:
            self.assertEqual(self.reader.call("messages", refs=["synthetic"], since=0, until=1), {"conversations": []})
        args, kwargs = run.call_args
        self.assertIsInstance(args[0], list)
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["env"]["PYTHONUTF8"], "1")
        self.assertEqual(kwargs["env"]["MESSAGING_ACCESS_CONFIG"], str(self.config))
        self.assertEqual(json.loads(kwargs["input"])["action"], "messages")

    def test_raw_stderr_is_never_returned(self):
        class Response:
            returncode = 1
            stdout = '{"ok":false,"error":{"code":"ACCESS_DENIED","message":"raw private identity"}}'
            stderr = "raw secret"
        with patch("wq_panel.access.subprocess.run", return_value=Response()):
            with self.assertRaises(AccessError) as error:
                self.reader.call("messages", refs=[], since=0, until=1)
        self.assertEqual(str(error.exception), "ACCESS_DENIED")

    def test_installer_pointer_keeps_custom_deployment(self):
        pointer = self.root / "WeChatQQAIPanel" / "access-config.json"
        pointer.parent.mkdir()
        pointer.write_text(json.dumps({"configPath": str(self.config)}), encoding="utf-8")
        with patch.dict("os.environ", {"LOCALAPPDATA": str(self.root), "MESSAGING_ACCESS_CONFIG": ""}):
            self.assertEqual(AccessClient().config_path, self.config)

    def test_broken_installer_pointer_never_falls_back(self):
        pointer = self.root / "WeChatQQAIPanel" / "access-config.json"
        pointer.parent.mkdir()
        pointer.write_text("broken", encoding="utf-8")
        with patch.dict("os.environ", {"LOCALAPPDATA": str(self.root), "MESSAGING_ACCESS_CONFIG": ""}):
            with self.assertRaises(AccessError):
                AccessClient()

    def test_cleanup_requires_pwsh_and_whitelists_summary(self):
        class Response:
            returncode = 0
            stdout = json.dumps({"Categories": [{"Category": "WeChatCache", "Files": 1, "MiB": 2,
                                                 "privatePath": "SECRET"}], "WeChatReaderActive": False})
        with patch("wq_panel.access.shutil.which", return_value="pwsh.exe"), patch(
                "wq_panel.access.subprocess.run", return_value=Response()) as run:
            data = self.reader.cache()
        self.assertEqual(run.call_args.args[0][0], "pwsh.exe")
        self.assertIn("-Json", run.call_args.args[0])
        self.assertNotIn("SECRET", str(data))
        self.assertEqual(data["categories"][0]["bytes"], 2 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
