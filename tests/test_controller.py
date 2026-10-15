from copy import deepcopy
from panel_fixtures import RecycleFixture
import threading
import unittest
from pathlib import Path

from wq_panel.app import Bridge, expose_bridge
from wq_panel.controller import Controller, PanelError, split_text
from wq_panel.storage import Store


class Reader:
    def __init__(self):
        self.allowed = {"r1", "r2"}
        self.catalog = [{"ref": "r1", "platform": "qq", "account": "account1", "conversation_id": "c1", "title": "测试群", "kind": "group"},
                        {"ref": "r2", "platform": "wechat", "account": "account2", "conversation_id": "c2", "title": "测试会话", "kind": "private"}]
        self.messages = [{"id": "m1", "ref": "r1", "timestamp": 1800099990, "sender": "测试发送者", "text": "请整理测试内容。", "type": "text", "source": "synthetic"}]
        self.calls = []
        self.complete = True
        self.policy = {"accounts": [], "revision": "test"}

    def call(self, action, **kwargs):
        self.calls.append((action, kwargs))
        if action == "catalog":
            return {"accounts": [{"platform": "qq", "account": "account1"}, {"platform": "wechat", "account": "account2"}], "conversations": deepcopy(self.catalog)}
        if action == "policy.get":
            return {"policy": self.policy}
        if action == "policy.set":
            self.policy = {"accounts": kwargs["accounts"], "revision": "changed"}
            self.allowed = {c["ref"] for c in self.catalog if any(
                a["platform"] == c["platform"] and a["account"] == c["account"] and
                ((c["conversation_id"] in a["conversations"]) == (a["mode"] == "allow"))
                for a in kwargs["accounts"])}
            return {"policy": self.policy}
        if action == "conversations":
            return {"conversations": [c for c in self.catalog if c["ref"] in self.allowed]}
        if action == "authorize":
            if not set(kwargs["refs"]).issubset(self.allowed):
                raise PanelError("UNAUTHORIZED")
            return {"revision": "test", "allowed": kwargs["refs"]}
        if action == "messages":
            refs = kwargs["refs"]
            return {"messages": [deepcopy(m) for m in self.messages if m["ref"] in refs and kwargs["since"] <= m["timestamp"] <= kwargs["until"]],
                    "coverage": [{"ref": ref, "complete": self.complete} for ref in refs], "policy_revision": "test"}
        raise ValueError(action)


class Model:
    def __init__(self):
        self.calls = []
        self.fail = False
        self.callback = None

    def generate(self, system, text, on_chunk, cancel):
        self.calls.append((system, text))
        if self.callback:
            self.callback()
        if self.fail:
            raise RuntimeError("secret-never-log")
        return "合成整理 [S1]"


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.temp = RecycleFixture()
        self.store = Store(Path(self.temp.name))
        self.store.settings["watched"] = ["r1"]
        self.reader = Reader()
        self.model = Model()
        self.controller = Controller(self.reader, self.store, lambda *_: self.model, clock=lambda: 1800100000)

    def tearDown(self):
        self.controller.stop()
        if self.controller.thread:
            self.controller.thread.join(2)
        self.temp.cleanup()

    def run_task(self, action="summarize", refs=None):
        self.controller.start(action, "brief", refs)
        self.controller.thread.join(3)
        self.assertFalse(self.controller.thread.is_alive())
        return self.controller.status()

    def test_fetch_never_calls_model(self):
        state = self.run_task("fetch")
        self.assertEqual(state["count"], 1)
        self.assertEqual(self.model.calls, [])
        self.assertIn("__fetch__:r1", self.store.cursors)

    def test_success_commits_and_result_rechecks_permissions(self):
        state = self.run_task()
        self.assertEqual(state["phase"], "done")
        self.assertIn("brief:r1", self.store.cursors)
        self.assertEqual(self.controller.result("brief")["result"]["messageCount"], 1)
        self.reader.allowed = set()
        self.reader.policy["revision"] = "revoked"
        self.assertIsNone(self.controller.result("brief")["result"])
        self.assertNotIn("brief", self.store.results)

    def test_partial_read_never_calls_model_or_commits(self):
        self.reader.complete = False
        state = self.run_task()
        self.assertEqual(state["error"]["code"], "INCOMPLETE_READ")
        self.assertFalse(self.store.cursors)
        self.assertFalse(self.model.calls)

    def test_model_failure_preserves_previous_result_and_cursor(self):
        self.run_task()
        old = deepcopy(self.store.cursors)
        old_result = deepcopy(self.store.results)
        self.reader.messages.append({**self.reader.messages[0], "id": "m2", "timestamp": 1800100000})
        self.model.fail = True
        state = self.run_task()
        self.assertEqual(state["phase"], "error")
        self.assertNotIn("secret", str(state))
        self.assertEqual(self.store.cursors, old)
        self.assertEqual(self.store.results, old_result)

    def test_revocation_during_model_does_not_commit(self):
        self.model.callback = lambda: self.reader.allowed.clear()
        state = self.run_task()
        self.assertEqual(state["phase"], "error")
        self.assertFalse(self.store.cursors)
        self.assertFalse(self.store.results)

    def test_cancel_during_model_does_not_commit(self):
        self.model.callback = self.controller.stop
        state = self.run_task()
        self.assertEqual(state["phase"], "cancelled")
        self.assertFalse(self.store.cursors)
        self.assertFalse(self.store.results)

    def test_chunking_preserves_oversized_messages(self):
        self.reader.messages[0]["text"] = "ABCDE" * 5000
        self.controller.chunk_limit = 1000
        state = self.run_task()
        self.assertEqual(state["phase"], "done")
        data_calls = [text for system, text in self.model.calls if "合并以下" not in system]
        self.assertGreater(len(data_calls), 20)
        self.assertEqual("".join(data_calls).count("ABCDE"), 5000)
        self.assertTrue(all(len(text) <= 1000 for text in data_calls))

    def test_cross_ref_response_is_rejected(self):
        original = self.reader.call
        def wrapped(action, **kwargs):
            data = original(action, **kwargs)
            if action == "messages":
                data["messages"].append({**self.reader.messages[0], "ref": "r2"})
            return data
        self.reader.call = wrapped
        self.assertEqual(self.run_task()["error"]["code"], "ACCESS_RESPONSE_INVALID")
        self.assertFalse(self.model.calls)

    def test_dedup_and_boundary_overlap(self):
        self.reader.messages = [{**self.reader.messages[0], "timestamp": 1800100000}] * 2
        self.assertEqual(self.run_task()["count"], 1)
        calls = len(self.model.calls)
        self.assertEqual(self.run_task()["count"], 0)
        self.assertEqual(len(self.model.calls), calls)

    def test_save_policy_drops_forbidden_watches_and_results(self):
        self.run_task()
        self.controller.save_policy([
            {"platform": "qq", "account": "account1", "mode": "deny", "conversations": ["c1"]},
            {"platform": "wechat", "account": "account2", "mode": "allow", "conversations": ["c2"]}], ["r1", "r2"])
        self.assertEqual(self.store.settings["watched"], ["r2"])
        self.assertFalse(self.store.results)

    def test_settings_never_store_secret_extra_fields(self):
        settings = deepcopy(self.store.settings)
        settings["model"]["api"]["api_key"] = "must-not-store"
        self.controller.save_settings(settings)
        self.assertNotIn("must-not-store", (self.store.root / "settings.json").read_text(encoding="utf-8"))

    def test_unexpected_exceptions_are_sanitized(self):
        bridge = Bridge(self.controller)
        self.reader.call = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("private account and token"))
        response = bridge.catalog()
        self.assertFalse(response["ok"])
        self.assertNotIn("private", str(response))

    def test_split_lossless(self):
        text = "中文\n" * 8000
        self.assertEqual("".join(split_text(text, 999)), text)

    def test_daily_unchanged_skips_model_but_new_message_rebuilds_day(self):
        def daily():
            self.controller.start("summarize", "daily")
            self.controller.thread.join(3)
        daily()
        self.assertEqual(len(self.model.calls), 1)
        daily()
        self.assertEqual(len(self.model.calls), 1)
        self.reader.messages.append({**self.reader.messages[0], "id": "m2", "text": "新的合成进展"})
        daily()
        self.assertEqual(len(self.model.calls), 2)
        self.assertEqual(self.store.results["daily"]["messageCount"], 2)

    def test_fetch_disk_failure_never_advances_memory_cursor(self):
        self.run_task("fetch")
        previous = deepcopy(self.store.cursors)
        self.reader.messages.append({**self.reader.messages[0], "id": "new", "timestamp": 1800100000})
        self.store.write = lambda *args: (_ for _ in ()).throw(OSError("disk failure"))
        self.assertEqual(self.run_task("fetch")["phase"], "error")
        self.assertEqual(self.store.cursors, previous)

    def test_reserved_fetch_preset_is_rejected(self):
        settings = deepcopy(self.store.settings)
        settings["presets"][0]["id"] = "__fetch__"
        with self.assertRaises(PanelError):
            self.controller.save_settings(settings)

    def test_damaged_policy_local_editor_can_repair(self):
        original = self.reader.call
        def wrapped(action, **kwargs):
            if action == "policy.get":
                raise PanelError("POLICY_INVALID")
            return original(action, **kwargs)
        self.reader.call = wrapped
        catalog = self.controller.catalog()
        self.assertIsNone(catalog["policy"])
        self.assertIn("POLICY_INVALID", catalog["warnings"])
        self.assertEqual(len(catalog["accounts"]), 2)

    def test_native_bridge_exposes_no_nested_reader_store_or_window(self):
        bridge = Bridge(self.controller)
        bridge.window = object()
        class Window:
            def expose(self, *functions):
                self.names = {function.__name__ for function in functions}
                self.functions = functions
        window = Window()
        expose_bridge(window, bridge)
        self.assertTrue({"start", "save_policy", "clean", "copy_result"}.issubset(window.names))
        self.assertFalse({"controller", "window", "reader", "write", "call", "load_url", "evaluate_js", "_call"} & window.names)
        self.assertTrue(all(callable(f) for f in window.functions))

    def test_idle_result_check_does_not_touch_message_source(self):
        self.run_task()
        self.reader.calls.clear()
        self.assertIsNotNone(self.controller.result("brief")["result"])
        self.assertEqual([action for action, _kwargs in self.reader.calls], ["policy.get"])


if __name__ == "__main__":
    unittest.main()
