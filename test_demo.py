"""Acceptance checks for the synthetic handoff walkthrough."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import relate

from demo import LocalModel, ScriptedModel, TOOLS, Trace, run_demo
from demo_store import (
    Denied,
    Gateway,
    SEED,
    advance_finding,
    approval_token,
    inspect_simulator,
    seed_simulator,
    verify_notice,
)


class DemoTest(unittest.TestCase):
    def setUp(self):
        work = TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.work = Path(work.name)
        self.trace = Trace("scripted-test")

    def run_script(self, approve=approval_token, withheld=()):
        return run_demo(
            self.work, ScriptedModel(), self.trace, approve, lambda _: None, withheld,
        )

    def test_handoff_updates_one_job_and_closes_on_independent_receipt(self):
        self.assertEqual(self.run_script(), "verified")
        events = self.trace.record["events"]
        restored = next(e for e in events if e["event"] == "restored")
        self.assertNotEqual(restored["prior_session"], restored["context"]["session"])
        self.assertEqual(restored["context"]["principal"], "Maya")
        self.assertEqual(restored["context"]["work"][0]["author"], "Ari")
        proof = next(e for e in events if e["event"] == "verified_notice")
        self.assertEqual(proof["receipt"]["elapsed"], 24)
        self.assertEqual(proof["receipt"]["job"], "notify-8")
        self.assertEqual(proof["receipt"]["recipient"], "north-customer-inbox")
        self.assertEqual(
            {j["id"]: j["hours"] for j in proof["after"]["jobs"]},
            {"notify-8": 24, "notify-9": 48, "monthly-north": 720, "monthly-south": 720},
        )
        self.assertIn("delivery_approval_denied", [e["event"] for e in events])
        with relate.connect(str(self.work / "handoff.rl"), read_only=True) as graph:
            gateway = Gateway(graph)
            context = gateway.context(gateway.bind("delivery"))
            self.assertEqual(context["work"][0]["state"], "verified")

    def test_each_missing_source_prevents_any_change(self):
        for key in ("handoff-note", "scheduler-change"):
            with self.subTest(withheld=key):
                work = self.work / key
                work.mkdir()
                trace = Trace("scripted-test")
                self.assertEqual(run_demo(
                    work, ScriptedModel(), trace,
                    lambda _: self.fail("Operations was asked to approve without evidence"),
                    lambda _: None, (key,),
                ), "unresolved")
                state = inspect_simulator(work / "scheduler.sqlite")
                self.assertEqual(state["receipts"], [])
                self.assertEqual(state["effect_count"], 0)

    def test_declining_approval_leaves_proposal_and_simulator_untouched(self):
        self.assertEqual(self.run_script(lambda _: ""), "approval_pending")
        self.assertEqual(inspect_simulator(self.work / "scheduler.sqlite")["effect_count"], 0)
        with relate.connect(str(self.work / "handoff.rl"), read_only=True) as graph:
            result = graph.execute("MATCH (p:Proposal) RETURN p.state AS state").data()
            self.assertEqual(result, [{"state": "proposed"}])

    def test_departed_actor_restricted_source_and_late_amendment(self):
        with relate.connect(":memory:") as graph:
            graph.execute(SEED)
            access = Gateway(graph)
            for key in ("former", "unknown"):
                with self.assertRaisesRegex(Denied, "^actor unavailable$"):
                    access.bind(key)
            delivery = access.bind("delivery")
            legal = access.bind("legal")
            for key in ("private-note", "missing"):
                with self.assertRaisesRegex(Denied, "^source unavailable$"):
                    access.source(delivery, key)
            with self.assertRaisesRegex(Denied, "^source unavailable$"):
                access.source(legal, "handoff-note")
            self.assertEqual(access.rule("north", 10, 10)["hours"], 48)
            self.assertEqual(access.rule("north", 10, 14)["hours"], 24)
            self.assertEqual(access.rule("south", 14, 14)["hours"], 48)
            with self.assertRaises(Denied):
                access.publish(legal, "draft")

    def test_effect_and_receipt_survive_reopen_before_acknowledgment(self):
        graph_path = str(self.work / "handoff.rl")
        simulator = self.work / "scheduler.sqlite"
        seed_simulator(simulator)
        before = inspect_simulator(simulator)
        with relate.connect(graph_path) as graph:
            graph.execute(SEED)
            access = Gateway(graph)
            event = access.publish(access.bind("legal"), "north-v2")["event"]
            delivery = access.bind("delivery")
            path = access.job_path(delivery, event)
            proposal = access.propose(
                delivery, event, path["job"], [path["note_source"], path["rename_source"]],
            )
            operations = access.bind("operations")
            with self.assertRaises(Denied):
                access.approve(operations, proposal, "APPROVE notify-9 north-v2 24")
            effect = access.approve(operations, proposal, approval_token(proposal))
            access.dispatch(operations, effect, simulator)
            finding = f"finding:{effect['id']}"
            advance_finding(simulator, finding, "north", reported=100, through=123)
            self.assertEqual(inspect_simulator(simulator)["receipts"], [])
            advance_finding(simulator, finding, "north", reported=100, through=124)
        with relate.connect(graph_path) as graph:
            effect = graph.execute("""
                MATCH (p:Proposal)-[:SCHEDULES]->(e:Effect {state:'pending'})
                RETURN e.id AS id, p.id AS proposal, p.job AS job, p.site AS site,
                       p.hours AS hours, p.revision AS revision
            """).single()
            access = Gateway(graph)
            access.dispatch(access.bind("operations"), effect, simulator)
            advance_finding(simulator, finding, "north", reported=100, through=124)
            receipt = verify_notice(before, inspect_simulator(simulator), effect)
            access.acknowledge(effect, receipt["finding"])
            result = graph.execute("MATCH (e:Effect) RETURN e.state AS state").single()
            self.assertEqual(result, {"state": "verified"})

    def test_unrepaired_scheduler_keeps_48_hour_due_time(self):
        simulator = self.work / "scheduler.sqlite"
        seed_simulator(simulator)
        advance_finding(simulator, "test-finding", "north", reported=100, through=124)
        self.assertEqual(inspect_simulator(simulator)["receipts"], [])
        advance_finding(simulator, "test-finding", "north", reported=100, through=148)
        self.assertEqual(inspect_simulator(simulator)["receipts"][0]["elapsed"], 48)

    def test_model_retries_malformed_arguments_before_calling_gateway(self):
        def reply(args):
            return {"message": {"role": "assistant", "tool_calls": [
                {"function": {"name": "read_context", "arguments": args}},
            ]}}

        model = LocalModel.__new__(LocalModel)
        replies = iter((reply({"identifier": "partnership"}), reply({})))
        model.request = lambda *args: next(replies)
        session = SimpleNamespace(
            messages=[], trace=self.trace, actor=SimpleNamespace(key="delivery", session="one"),
        )
        args = model.arguments(session, TOOLS["read_context"], "Restore your partnership.")
        self.assertEqual(args, {})
        self.assertEqual(len(self.trace.record["events"]), 2)
        self.assertEqual([m["role"] for m in session.messages], ["user", "user", "assistant"])


if __name__ == "__main__":
    unittest.main()
