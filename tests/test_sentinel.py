import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).parents[1] / "mac-space-sentinel.py"
SPEC = importlib.util.spec_from_file_location("sentinel", MODULE)
sentinel = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sentinel)


class SentinelTests(unittest.TestCase):
    def test_scan_ranks_large_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "small").write_bytes(b"a")
            (root / "large.bin").write_bytes(b"x" * 64)
            result = sentinel.scan(root, 32, 100, 10, [])
            self.assertEqual(result["files_seen"], 2)
            self.assertEqual(result["large_files"][0]["path"], str((root / "large.bin").resolve()))

    def test_plan_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = Path(tmp) / "plan.json"
            plan.write_text(json.dumps({"kind": "trash-plan", "actions": []}))
            args = type("Args", (), {"yes_i_understand": False, "apply_plan": str(plan), "dry_run": True})()
            with self.assertRaises(SystemExit):
                sentinel.apply_plan(args)

    def test_trash_target_rejects_outside_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                sentinel.validate_trash_target(tmp)

    def test_assessment_marks_photos_as_guided_human_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report = {"inventory": {"top_level_directories_recursive": [], "large_files": [{"path": "/home/test/Pictures/Photos Library.photoslibrary/a.mov"}]}}
            report_path.write_text(json.dumps(report))
            packet = sentinel.assessment_template(report, report_path)
            self.assertEqual(packet["actions"][0]["id"], "photos-icloud-guidance")
            self.assertEqual(packet["actions"][0]["risk"], "human-confirmation")

    def test_assessment_rejects_unbound_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "report.json"
            report = {"inventory": {"top_level_directories_recursive": [], "large_files": []}}
            report_path.write_text(json.dumps(report))
            packet = sentinel.assessment_template(report, report_path)
            packet["evidence"].append({"id": "invented", "path": "/bad", "bytes": 1, "category": "other"})
            with self.assertRaises(ValueError):
                sentinel.validate_assessment(packet, report_path)


if __name__ == "__main__":
    unittest.main()
