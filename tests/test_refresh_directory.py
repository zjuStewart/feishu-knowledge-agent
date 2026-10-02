"""Exercise pagination, changed paths and preservation without touching Feishu."""
import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

script = Path(__file__).resolve().parents[1] / "skills/lark-wiki-directory/scripts/refresh_directory.py"
spec = importlib.util.spec_from_file_location("wiki_directory_sync", script)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def node(token, parent="", title=None, child=False):
    return {"node_token": token, "parent_node_token": parent, "title": title or token,
            "space_id": "test", "has_child": child, "obj_type": "docx", "obj_token": "doc_" + token}


class RefreshAcceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [patch.object(sync, "ROOT", self.root), patch.object(sync, "SETTINGS", {
            "space_id": "test", "space_name": "Test", "base_url": "https://example.invalid", "shared_context_root": "core"})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.temp.cleanup()

    def test_paginated_tree_and_renamed_parent(self):
        def pages(parent, cursor=None):
            if parent is None and cursor is None:
                return {"nodes": [node("core", title="A [core]", child=True)], "has_more": True, "page_token": "next"}
            if parent is None:
                return {"nodes": [node("meetings")], "has_more": False}
            return {"nodes": [node("child", parent="core")], "has_more": False}
        with patch.object(sync, "list_nodes", pages):
            first = sync.refresh()
            second = sync.refresh()
        self.assertEqual(first["nodes"], 3)
        self.assertEqual(first["shared_context_nodes"], 2)
        self.assertFalse(second["directory_changed"])
        text = (self.root / "工作知识库目录.md").read_text()
        self.assertIn("A \\[core\\]", text)
        self.assertLess(text.index("child"), text.index("meetings"))
        with patch.object(sync, "list_nodes", return_value={"nodes": [node("core", title="Renamed")], "has_more": False}):
            third = sync.refresh()
        self.assertEqual(third["changes"]["updated"], ["core"])
        self.assertEqual(third["changes"]["removed_from_visible_index"], ["child", "meetings"])

    def test_read_failure_preserves_previous_directory(self):
        with patch.object(sync, "list_nodes", return_value={"nodes": [node("core")], "has_more": False}):
            sync.refresh()
        before = (self.root / "knowledge-map.json").read_bytes()
        with patch.object(sync, "list_nodes", side_effect=RuntimeError("mock credential text must not be recorded")):
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit):
                sync.main()
        self.assertEqual(before, (self.root / "knowledge-map.json").read_bytes())
        status = json.loads((self.root / "sync-status.json").read_text())
        self.assertTrue(status["previous_directory_preserved"])
        self.assertNotIn("credential text", json.dumps(status))

    def test_repeated_cursor_rejects_incomplete_snapshot(self):
        with patch.object(sync, "list_nodes", return_value={"nodes": [node("core")], "has_more": True, "page_token": "repeat"}):
            with self.assertRaises(RuntimeError):
                sync.refresh()
        self.assertFalse((self.root / "knowledge-map.json").exists())

    def test_portable_profile_and_default_profile_use_same_entry(self):
        settings = self.root / "settings.json"
        settings.write_text(json.dumps(sync.SETTINGS))
        profile = self.root / "profile.json"
        profile.write_text(json.dumps({"settings_path": "settings.json", "output_dir": "index"}))
        with patch.object(sync, "DEFAULT_CONFIG", profile), patch.object(sync, "list_nodes", return_value={"nodes": [node("core")], "has_more": False}):
            with contextlib.redirect_stdout(io.StringIO()):
                sync.cli_main([])
                sync.cli_main(["--config", str(profile)])
        status = json.loads((self.root / "index/sync-status.json").read_text())
        self.assertTrue(status["ok"])
        self.assertFalse(status["directory_changed"])
        self.assertEqual(json.loads((self.root / "index/knowledge-map.json").read_text())["space_id"], "test")

    def test_missing_profile_does_not_call_feishu(self):
        with patch.object(sync, "list_nodes") as call:
            with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(SystemExit) as error:
                sync.cli_main(["--config", str(self.root / "missing.json")])
        self.assertEqual(error.exception.code, 2)
        call.assert_not_called()

    def test_removed_background_root_updates_directory_and_requests_replacement(self):
        with patch.object(sync,'list_nodes',return_value={'nodes':[node('core')],'has_more':False}):sync.refresh()
        with patch.object(sync,'list_nodes',return_value={'nodes':[node('remaining')],'has_more':False}):result=sync.refresh()
        current=json.loads((self.root/'knowledge-map.json').read_text())
        self.assertEqual([n['node_token'] for n in current['nodes']],['remaining'])
        self.assertFalse(current['shared_context_root_visible']);self.assertTrue(result['needs_user_action'])
        self.assertEqual(result['changes']['removed_from_visible_index'],['core'])


if __name__ == "__main__":
    unittest.main()
