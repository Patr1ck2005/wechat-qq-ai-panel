import json
from pathlib import Path
from panel_fixtures import RecycleFixture
import unittest
import threading
from unittest.mock import patch

from wq_panel.access import AccessClient, AccessError
from wq_panel.controller import safe_error


class AccessClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = RecycleFixture()
        self.root = Path(self.temp.name)
        self.user_home = patch("wq_panel.access.Path.home", return_value=self.root)
        self.user_home.start()
        self.environment = patch.dict("os.environ", {"LOCALAPPDATA": str(self.root), "MESSAGING_ACCESS_CONFIG": ""})
        self.environment.start()
        self.python = self.root / "python.exe"
        self.python.write_bytes(b"synthetic")
        self.config = self.root / "deployment.json"
        self.config.write_text(json.dumps({"pythonExe": str(self.python), "projectRoot": str(self.root)}), encoding="utf-8")
        self.reader = AccessClient(self.config)

    def tearDown(self):
        self.temp.cleanup()
        self.environment.stop()
        self.user_home.stop()

    def test_regular_user_config_precedes_legacy_without_invalid_fallback(self):
        regular = self.root / ".local/share/wechat-qq-access/deployment.json"
        legacy = self.root / "MessagingAccess/deployment.json"
        regular.parent.mkdir(parents=True)
        legacy.parent.mkdir()
        regular.write_bytes(self.config.read_bytes())
        legacy.write_bytes(self.config.read_bytes())
        reader = AccessClient()
        self.assertEqual(reader.config_path, regular)
        regular.write_text("invalid", encoding="utf-8")
        with self.assertRaises(AccessError) as error:
            reader._deployment()
        self.assertEqual(error.exception.code, "DEPLOYMENT_CONFIG_INVALID")

    def test_legacy_default_remains_available_when_regular_config_absent(self):
        legacy = self.root / "MessagingAccess/deployment.json"
        legacy.parent.mkdir()
        legacy.write_bytes(self.config.read_bytes())
        self.assertEqual(AccessClient().config_path, legacy)

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

    def diagnostic(self):
        path = self.root / "WeChatQQAIPanel" / "connection-diagnostic.json"
        content = path.read_text(encoding="utf-8")
        self.assertLessEqual(len(content.encode("utf-8")), 2048)
        return json.loads(content)

    def test_missing_config_has_fixed_nonprivate_diagnostic(self):
        missing = self.root / "PRIVATE-ACCOUNT-TOKEN-never-written.json"
        with self.assertRaises(AccessError) as error:
            AccessClient(missing)._deployment()
        self.assertEqual(error.exception.code, "DEPLOYMENT_CONFIG_MISSING")
        data = self.diagnostic()
        self.assertEqual(data["stage"], "config")
        self.assertEqual(data["configSource"], "explicit")
        self.assertFalse(data["configExists"])
        self.assertNotIn("PRIVATE-ACCOUNT-TOKEN", json.dumps(data))
        self.assertNotIn(str(self.root), json.dumps(data))
        self.assertNotIn("不存在", str(error.exception))

    def test_json_shape_python_and_root_have_distinct_codes(self):
        cases = [
            ("PRIVATE-BROKEN-JSON", "DEPLOYMENT_CONFIG_INVALID"),
            (json.dumps([]), "DEPLOYMENT_CONFIG_INVALID"),
            (json.dumps({"pythonExe": 123, "projectRoot": str(self.root)}), "DEPLOYMENT_CONFIG_INVALID"),
            (json.dumps({"pythonExe": str(self.root / "missing-python.exe"), "projectRoot": str(self.root)}), "DEPLOYMENT_PYTHON_MISSING"),
            (json.dumps({"pythonExe": str(self.python), "projectRoot": str(self.root / "missing-root")}), "DEPLOYMENT_ROOT_MISSING"),
        ]
        for content, code in cases:
            with self.subTest(code=code):
                self.config.write_text(content, encoding="utf-8")
                with self.assertRaises(AccessError) as error:
                    self.reader._deployment()
                self.assertEqual(error.exception.code, code)
                self.assertEqual(self.diagnostic()["code"], code)
                self.assertNotIn("PRIVATE-BROKEN-JSON", json.dumps(self.diagnostic()))
                self.assertNotEqual(safe_error(error.exception)["message"], "操作未完成，请检查接入或模型设置。")

    def test_environment_override_is_observable_but_never_falls_back(self):
        directory = self.root / "WeChatQQAIPanel"
        directory.mkdir()
        (directory / "access-config.json").write_text(json.dumps({"configPath": str(self.config)}), encoding="utf-8")
        with patch.dict("os.environ", {"MESSAGING_ACCESS_CONFIG": str(self.root / "stale-private-override.json")}):
            automatic = AccessClient()
            with self.assertRaises(AccessError):
                automatic._deployment()
        data = self.diagnostic()
        self.assertEqual(data["configSource"], "environment")
        self.assertTrue(data["pointerExists"])
        self.assertTrue(data["pointerValid"])
        self.assertFalse(data["selectedMatchesPointer"])
        self.assertFalse(data["selectedMatchesDefault"])
        self.assertEqual(data["code"], "DEPLOYMENT_CONFIG_MISSING")
        self.assertNotIn("stale-private-override", json.dumps(data))

    def test_pointer_is_reselected_after_installer_changes(self):
        directory = self.root / "WeChatQQAIPanel"
        directory.mkdir()
        pointer = directory / "access-config.json"
        pointer.write_text(json.dumps({"configPath": str(self.config)}), encoding="utf-8")
        automatic = AccessClient()
        other = self.root / "other-deployment.json"
        other.write_text(json.dumps({"pythonExe": str(self.python), "projectRoot": str(self.root), "synthetic": True}), encoding="utf-8")
        pointer.write_text(json.dumps({"configPath": str(other)}), encoding="utf-8")
        self.assertTrue(automatic._deployment()["synthetic"])
        self.assertEqual(automatic.config_path, other)
        # Explicit configuration cannot be redirected by either pointer or env.
        with patch.dict("os.environ", {"MESSAGING_ACCESS_CONFIG": str(self.root / "missing.json")}):
            self.assertNotIn("synthetic", self.reader._deployment())
            self.assertEqual(self.reader.config_path, self.config)

    def test_corrupted_pointer_records_fail_closed_source(self):
        directory = self.root / "WeChatQQAIPanel"
        directory.mkdir()
        (directory / "access-config.json").write_text("PRIVATE-INVALID-POINTER", encoding="utf-8")
        with self.assertRaises(AccessError) as error:
            AccessClient()
        self.assertEqual(error.exception.code, "DEPLOYMENT_POINTER_INVALID")
        data = self.diagnostic()
        self.assertEqual(data["configSource"], "installer_pointer")
        self.assertTrue(data["pointerExists"])
        self.assertFalse(data["pointerValid"])
        self.assertEqual(data["exceptionType"], "JSONDecodeError")
        self.assertNotIn("PRIVATE-INVALID-POINTER", json.dumps(data))

    def test_read_exception_only_records_exception_type(self):
        with patch.object(Path, "read_text", side_effect=PermissionError("PRIVATE-RAW-ERROR")):
            with self.assertRaises(AccessError) as error:
                self.reader._deployment()
        self.assertEqual(error.exception.code, "DEPLOYMENT_CONFIG_UNREADABLE")
        self.assertEqual(self.diagnostic()["exceptionType"], "PermissionError")
        self.assertNotIn("PRIVATE-RAW-ERROR", json.dumps(self.diagnostic()))

    def test_default_source_and_pointer_matches_are_boolean_only(self):
        automatic = AccessClient()
        with self.assertRaises(AccessError):
            automatic._deployment()
        data = self.diagnostic()
        self.assertEqual(data["configSource"], "default")
        self.assertTrue(data["selectedMatchesDefault"])
        self.assertFalse(data["pointerExists"])
        expected = {"schemaVersion", "stage", "code", "configSource", "pointerExists", "pointerValid",
                    "selectedMatchesPointer", "selectedMatchesDefault", "configExists", "pythonExists", "rootExists",
                    "exceptionType"}
        self.assertEqual(set(data), expected)
        for field in expected - {"schemaVersion", "stage", "code", "configSource", "exceptionType"}:
            self.assertIs(type(data[field]), bool)

    def test_concurrent_selection_cannot_reset_inflight_existence_checks(self):
        entered, release, second_started, second_done = (threading.Event() for _ in range(4))
        failures, deployments = [], []
        original = Path.is_file
        def pause_config_check(path):
            if path == self.config and threading.current_thread().name == "deployment-check":
                entered.set()
                if not release.wait(3):
                    raise RuntimeError("SYNTHETIC_TIMEOUT")
            return original(path)
        def first():
            try:
                deployments.append(self.reader._deployment())
            except Exception as exc:
                failures.append(exc)
        def second():
            second_started.set()
            try:
                self.reader._select_config()
            except Exception as exc:
                failures.append(exc)
            finally:
                second_done.set()
        a = threading.Thread(target=first, name="deployment-check")
        b = threading.Thread(target=second, name="concurrent-selection")
        with patch.object(Path, "is_file", pause_config_check):
            try:
                a.start()
                self.assertTrue(entered.wait(2))
                b.start()
                self.assertTrue(second_started.wait(2))
                self.assertFalse(second_done.wait(0.2), "selection reset an in-flight diagnostic state")
            finally:
                release.set()
                a.join(3)
                if b.ident:
                    b.join(3)
        self.assertFalse(failures)
        self.assertEqual(len(deployments), 1)
        self.assertTrue(second_done.is_set())

    def test_slow_access_subprocess_does_not_hold_configuration_lock(self):
        child_started, release, checked = (threading.Event() for _ in range(3))
        failures = []
        class Response:
            returncode = 0
            stdout = '{"ok":true,"data":{"policy":null}}'
        def slow_child(*args, **kwargs):
            child_started.set()
            if not release.wait(3):
                raise RuntimeError("SYNTHETIC_TIMEOUT")
            return Response()
        def call():
            try:
                self.reader.call("policy.get")
            except Exception as exc:
                failures.append(exc)
        def inspect():
            try:
                self.reader._deployment()
                checked.set()
            except Exception as exc:
                failures.append(exc)
        a = threading.Thread(target=call)
        b = threading.Thread(target=inspect)
        with patch("wq_panel.access.subprocess.run", side_effect=slow_child):
            try:
                a.start()
                self.assertTrue(child_started.wait(2))
                b.start()
                self.assertTrue(checked.wait(2), "long-running child blocked configuration checks")
            finally:
                release.set()
                a.join(3)
                if b.ident:
                    b.join(3)
        self.assertFalse(failures)


if __name__ == "__main__":
    unittest.main()
