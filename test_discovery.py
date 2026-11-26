"""Acceptance checks for Product discovery and retained proposals."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import relate

from demo import ScriptedModel, Trace, run_demo, run_discovery
from demo_discovery import Discovery, SEED_DISCOVERY
from demo_store import Denied, SEED, approval_token, inspect_simulator


class DiscoveryTest(unittest.TestCase):
    def setUp(self):
        work = TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.work = Path(work.name)
        self.trace = Trace("scripted-test")
        self.model = ScriptedModel()

    def run_handoff(self):
        self.assertEqual(
            run_demo(self.work, self.model, self.trace, approval_token, lambda _: None),
            "verified",
        )

    def test_trial_retains_independent_sources_owner_question_and_verified_history(self):
        self.run_handoff()
        simulator = self.work / "scheduler.sqlite"
        before = inspect_simulator(simulator)
        self.assertEqual(
            run_discovery(self.work, self.model, self.trace, lambda _: None),
            "discovery_proposed",
        )
        result = self.trace.record["events"][-1]
        self.assertEqual(result["event"], "discovery_retained")
        retained = result["trial"]
        self.assertEqual(retained["owner"], "Noor")
        self.assertEqual(retained["site"], "north")
        self.assertEqual(retained["status"], "awaiting-review")
        self.assertNotEqual(result["reader_session"], retained["author_session"])
        self.assertEqual(
            {row["source"] for row in retained["evidence"]},
            {"delivery-shift-17", "customer-ticket-51", "ack-alert-spec"},
        )
        self.assertEqual(result["handoff"]["state"], "verified")
        self.assertEqual(inspect_simulator(simulator), before)

    def test_copy_and_an_unavailable_source_cannot_support_a_trial(self):
        self.run_handoff()
        self.assertEqual(
            run_discovery(self.work, self.model, self.trace, lambda _: None, copied_only=True),
            "discovery_unresolved",
        )
        result = self.trace.record["events"][-1]
        self.assertEqual((result["independent_origins"], result["proposals"]), (1, 0))
        with relate.connect(str(self.work / "handoff.rl")) as graph:
            gateway = Discovery(graph, day=16, withheld=("customer-ticket-51",))
            actor = gateway.bind("product")
            self.assertEqual(len(gateway.signals(actor)["copies"]), 1)
            for customer in ("delivery-shift-forward", "customer-ticket-51"):
                with self.subTest(customer_source=customer), self.assertRaises(Denied):
                    gateway.save_trial(
                        actor, "delivery-shift-17", customer, "acknowledgment-alert",
                        "Check the connector.", "Does it emit the event?",
                    )
            self.assertEqual(graph.execute("MATCH (t:Trial) RETURN count(t) AS count").single(),
                             {"count": 0})

    def test_product_scope_and_recorded_time_bound_the_discovery(self):
        with relate.connect(":memory:") as graph:
            graph.execute(SEED)
            graph.execute(SEED_DISCOVERY)
            early = Discovery(graph, day=14)
            actor = early.bind("product")
            self.assertEqual(
                [row["source"] for row in early.signals(actor)["independent"]],
                ["delivery-shift-17"],
            )
            current = Discovery(graph, day=16)
            with self.assertRaisesRegex(Denied, "^operation unavailable$"):
                current.capability(current.bind("delivery"))
            for source in ("customer-private", "missing"):
                with self.subTest(source=source), self.assertRaisesRegex(Denied, "^source unavailable$"):
                    current.source(actor, source)
            graph.execute("MATCH (n:Signal {source:'delivery-shift-forward'}) SET n.copy = false")
            rows = current.signals(actor)["independent"]
            self.assertEqual({row["origin"] for row in rows}, {"shift-17", "support-51"})
            self.assertEqual(len(rows), 2)

    def test_retention_rechecks_current_scope_and_preserves_original_proposal(self):
        self.run_handoff()
        self.assertEqual(
            run_discovery(self.work, self.model, self.trace, lambda _: None),
            "discovery_proposed",
        )
        trial = self.trace.record["events"][-1]["trial"]
        with relate.connect(str(self.work / "handoff.rl")) as graph:
            current = Discovery(graph, day=16)
            product = current.bind("product")
            repeat = current.save_trial(
                product, "delivery-shift-17", "customer-ticket-51", "acknowledgment-alert",
                "Different proposed action.", "A different question?",
            )
            self.assertEqual(repeat["id"], trial["id"])
            readback = current.retained(product, trial["id"])
            self.assertEqual(readback["next_step"], trial["next_step"])
            self.assertEqual(readback["author_session"], trial["author_session"])
            restricted = Discovery(graph, day=16, withheld=("customer-ticket-51",))
            with self.assertRaisesRegex(Denied, "^trial unavailable$"):
                restricted.retained(product, trial["id"])


if __name__ == "__main__":
    unittest.main()
