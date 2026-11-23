"""The whole demo, in manifest order, on one seed — exactly what a reviewer clicks through in the UI."""
import json

from conftest import SAMPLES, submit


def test_manifest_order_matches_expectations(runner):
    for m in json.loads((SAMPLES / "manifest.json").read_text()):
        r = submit(runner, m["id"])
        assert r["status"] == "done", (m["id"], r["error"])
        assert (r["decision"], r["deciding_rule"]) == (m["expected_decision"], m["expected_rule"]), \
            (m["id"], r["deciding_message"])
