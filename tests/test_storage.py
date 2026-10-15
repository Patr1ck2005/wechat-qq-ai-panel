import json
from pathlib import Path
from panel_fixtures import RecycleFixture
import unittest

from wq_panel.storage import Store


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = RecycleFixture()
        self.root = Path(self.temp.name)
        self.store = Store(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def test_only_latest_result_per_preset(self):
        for n in range(10):
            self.store.commit_result("brief", {"text": str(n), "refs": ["r1"]}, {"brief:r1": n})
        self.assertEqual(len(self.store.results), 1)
        self.assertEqual(self.store.results["brief"]["text"], "9")
        self.assertEqual(json.loads((self.root / "state.json").read_text(encoding="utf-8"))["cursors"]["brief:r1"], 9)

    def test_active_and_webview_cleanup_skipped(self):
        (self.root / "dsh").mkdir()
        (self.root / "dsh" / "state").write_text("protected")
        self.assertTrue(self.store.clean("dsh", busy=True)["skipped"])
        self.assertTrue(self.store.clean("webview")["skipped"])
        self.assertTrue((self.root / "dsh" / "state").exists())

    def test_cleanup_passes_exact_owned_path_to_recycle(self):
        self.store.commit_result("brief", {"text": "x"}, {"brief:r1": 5})
        # Test double uses a reversible move to a synthetic bin, never Windows cleanup.
        seen = []
        def recycler(path):
            seen.append(path)
            path.rename(self.root / "synthetic-bin.json")
        result = self.store.clean("results", recycler=recycler)
        self.assertEqual(seen, [self.root / "state.json"])
        self.assertTrue(result["recycled"])
        self.assertEqual(result["spaceFreed"], 0)
        self.assertTrue((self.root / "synthetic-bin.json").exists())
        self.assertEqual(self.store.cursors, {"brief:r1": 5})
        self.assertEqual(self.store.results, {})

    def test_failed_recycle_never_falls_back(self):
        self.store.commit_result("brief", {"text": "x"}, {})
        def fail(path):
            raise OSError("failed")
        with self.assertRaises(OSError):
            self.store.clean("results", recycler=fail)
        self.assertTrue((self.root / "state.json").exists())

    def test_unknown_category_and_originals_protected(self):
        (self.root / "keys.json").write_text("private")
        for category in ["../keys.json", "settings", "keys", "All"]:
            with self.assertRaises(ValueError):
                self.store.clean(category)
        self.assertEqual((self.root / "keys.json").read_text(), "private")

    def test_revocation_invalidates_multi_conversation_result(self):
        self.store.results = {"brief": {"refs": ["a", "b"]}, "daily": {"refs": ["b"]}}
        self.store.invalidate({"b"})
        self.assertEqual(list(self.store.results), ["daily"])

    def test_atomic_write_failure_preserves_both_old_values(self):
        self.store.commit_result("brief", {"text": "old", "refs": []}, {"brief:r1": 1})
        original = (self.root / "state.json").read_bytes()
        def fail(*args):
            raise OSError("simulated disk failure")
        self.store.write = fail
        with self.assertRaises(OSError):
            self.store.commit_result("brief", {"text": "new", "refs": []}, {"brief:r1": 2})
        self.assertEqual(self.store.cursors, {"brief:r1": 1})
        self.assertEqual(self.store.results["brief"]["text"], "old")
        self.assertEqual((self.root / "state.json").read_bytes(), original)

    def test_webview_cleanup_scheduled_and_only_before_start(self):
        (self.root / "webview").mkdir()
        (self.root / "webview" / "cache").write_text("synthetic")
        self.store.schedule_webview_cleanup()
        self.assertTrue(self.store.preview()[-1]["scheduled"])
        self.assertTrue(self.store.clean("webview")["skipped"])
        def recycler(path):
            path.rename(self.root / "synthetic-webview-bin")
        self.store.startup_cleanup(recycler=recycler)
        self.assertFalse((self.root / "webview").exists())
        self.assertFalse(self.store.settings["cleanupWebviewOnNextStart"])


if __name__ == "__main__":
    unittest.main()
