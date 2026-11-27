"""Checks for key-free replay and scoped judge projections."""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from judge_replay import RECORDING, ReplayMismatch, replay
from judge_view import build_views


class JudgeReplayTest(unittest.TestCase):
    def run_modified(self, change):
        recording = json.loads(RECORDING.read_text())
        change(recording["events"])
        with TemporaryDirectory() as temp:
            path = Path(temp) / "recording.json"
            path.write_text(json.dumps(recording))
            return replay(path, say=lambda _: None)

    def test_replay_rebuilds_scoped_views_from_verified_effects(self):
        result = replay(say=lambda _: None)
        self.assertEqual(result["mode"], "judge-replay")
        self.assertEqual(result["status"], "discovery_proposed")
        views = build_views(result)
        legal = json.dumps(views[("respond", "legal")])
        delivery = json.dumps(views[("respond", "delivery")])
        product = views[("discover", "product")]
        verifier = json.dumps(views[("respond", "verifier")])
        self.assertIn("clause-2", legal)
        self.assertNotIn("notify-8", legal)
        self.assertIn("scheduler-change", delivery)
        self.assertNotIn("north-customer-inbox", delivery)
        self.assertIn("north-customer-inbox", verifier)
        self.assertIn("notify-9", verifier)
        product_nodes = {node["id"]: node for node in product["nodes"]}
        readback = product_nodes[product["focus"]]["readback"]
        handoff, pending = readback
        retained = next(event for event in result["events"] if event["event"] == "discovery_retained")
        self.assertEqual(handoff["title"], "Verified North handoff")
        self.assertIn(retained["handoff"]["author"], handoff["detail"])
        self.assertEqual(pending["title"], "Pending one-site trial")
        self.assertEqual(dict(pending["facts"]), {
            "Owner": retained["trial"]["owner"], "Open question": retained["trial"]["question"],
        })
        self.assertEqual(dict(product_nodes["trial"]["facts"])["State"], "Awaiting review")
        self.assertNotIn("Handoff read back", dict(product_nodes["trial"]["facts"]))
        self.assertNotIn("customer-private", json.dumps(product))
        self.assertNotIn(("remember", "product"), views)

    def test_rejects_effect_receipt_that_fresh_execution_cannot_reproduce(self):
        def change(events):
            receipt = next(event for event in events if event["event"] == "verified_notice")
            receipt["receipt"]["elapsed"] = 25

        with self.assertRaisesRegex(ReplayMismatch, "fresh read or effect changed at verified_notice"):
            self.run_modified(change)

    def test_rejects_recorded_token_for_another_job(self):
        def change(events):
            approval = next(event for event in events if event["event"] == "approved")
            approval["approval"]["job"] = "notify-9"

        with self.assertRaisesRegex(ReplayMismatch, "recorded approval differs on job"):
            self.run_modified(change)

    def test_rejects_tool_argument_without_matching_native_call(self):
        def change(events):
            proposal = next(event for event in events if event.get("tool") == "save_trial")
            proposal["arguments"]["question"] = "Unrecorded question?"

        with self.assertRaisesRegex(ReplayMismatch, "missing its native model request"):
            self.run_modified(change)


if __name__ == "__main__":
    unittest.main()
