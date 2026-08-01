import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).parents[1] / "integrations" / "synodai" / "mac_space_sentinel_connector.py"
SPEC = importlib.util.spec_from_file_location("connector", MODULE)
connector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(connector)


def request(root: Path, **updates):
    base = {"schema": connector.REQUEST_SCHEMA, "operation": "scan", "root": str(root), "output_name": "fixture",
            "min_file_mib": 1, "top": 10, "max_files": 100}
    base.update(updates)
    return base


class ConnectorTests(unittest.TestCase):
    def test_execute_creates_host_sandbox_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "input"; root.mkdir(); (root / "large.bin").write_bytes(b"a" * 2048)
            out = Path(tmp) / "out"; out.mkdir()
            response = connector.execute(request(root), sentinel=Path(__file__).parents[1] / "mac-space-sentinel.py",
                                         allowed_roots=[root], output_base=out)
            self.assertEqual(response["status"], "allowed")
            self.assertTrue(Path(response["report"]).is_file())

    def test_rejects_root_outside_grant(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "input"; root.mkdir()
            other = Path(tmp) / "other"; other.mkdir()
            with self.assertRaises(ValueError):
                connector.validate(request(root), [other])

    def test_rejects_extra_model_selected_field(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); rogue = request(root, command="rm")
            with self.assertRaises(ValueError):
                connector.validate(rogue, [root])
