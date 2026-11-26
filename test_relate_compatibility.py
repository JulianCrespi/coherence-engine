"""Check the demo's candidate queries against the pinned embedded Relate binding."""

import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory

import relate


SEED = """
CREATE (delivery:Agent {id: 'delivery'}), (maya:Person {id: 'maya'}),
       (former:Agent {id: 'former'}), (ari:Person {id: 'ari'}),
       (legal:Agent {id: 'legal'}), (kai:Person {id: 'kai'}),
       (current:Assignment {role: 'Delivery', starts: 10, ends: 999}),
       (retired:Assignment {role: 'Delivery', starts: 1, ends: 10}),
       (counsel:Assignment {role: 'Legal', starts: 1, ends: 999}),
       (handoff:Observation {id: 'handoff-note', recorded: 9}),
       (review:Observation {id: 'legal-review', recorded: 14}),
       (delivery)-[:SERVES]->(maya), (delivery)-[:ASSIGNED_TO]->(current),
       (former)-[:SERVES]->(ari), (former)-[:ASSIGNED_TO]->(retired),
       (legal)-[:SERVES]->(kai), (legal)-[:ASSIGNED_TO]->(counsel),
       (current)-[:CAN_READ {starts: 10, ends: 999}]->(handoff),
       (retired)-[:CAN_READ {starts: 1, ends: 10}]->(handoff),
       (counsel)-[:CAN_READ {starts: 1, ends: 999}]->(review),
       (handoff)-[:AUTHORED_BY]->(ari), (review)-[:AUTHORED_BY]->(kai),
       (north:Site {id: 'north'}), (south:Site {id: 'south'}),
       (current)-[:RESPONSIBLE_FOR]->(north), (retired)-[:RESPONSIBLE_FOR]->(north),
       (baseline:Rule {id: 'base', hours: 48, effective: 1, recorded: 1, state: 'accepted'}),
       (amendment:Rule {id: 'north-v2', hours: 24, effective: 10, recorded: 14, state: 'accepted'}),
       (draft:Rule {id: 'draft', hours: 12, effective: 13, recorded: 13, state: 'unsigned'}),
       (baseline)-[:APPLIES_TO]->(north), (baseline)-[:APPLIES_TO]->(south),
       (amendment)-[:APPLIES_TO]->(north), (draft)-[:APPLIES_TO]->(north),
       (note:WorkNote {id: 'dependency', scope: 'delivery', recorded: 9}),
       (component:Component {id: 'notice-component', scope: 'delivery'}),
       (rename:ChangeRecord {id: 'rename', scope: 'delivery', recorded: 13}),
       (hidden:ChangeRecord {id: 'restricted-rename', scope: 'private', recorded: 13}),
       (target:Job {id: 'notify-8', scope: 'delivery'}),
       (sibling:Job {id: 'notify-9', scope: 'delivery'}),
       (north)-[:MAPPED_BY {scope: 'delivery'}]->(note),
       (note)-[:IDENTIFIES {scope: 'delivery'}]->(component),
       (component)-[:REVISED_BY {scope: 'delivery'}]->(rename),
       (component)-[:REVISED_BY {scope: 'delivery'}]->(hidden),
       (rename)-[:NAMES {scope: 'delivery'}]->(target),
       (hidden)-[:NAMES {scope: 'delivery'}]->(sibling)
"""

BOOT_CONTEXT = """
MATCH (a:Agent {id: $agent})-[:SERVES]->(p:Person),
      (a)-[:ASSIGNED_TO]->(r:Assignment)-[g:CAN_READ]->(o:Observation)-[:AUTHORED_BY]->(author:Person)
WHERE r.starts <= $day AND $day < r.ends
  AND g.starts <= $day AND $day < g.ends AND o.recorded <= $day
RETURN a.id AS agent, p.id AS principal, r.role AS role, o.id AS observation, author.id AS author
"""

DEPENDENCY = """
MATCH (s:Site {id: $site})-[m:MAPPED_BY]->(n:WorkNote)-[i:IDENTIFIES]->(c:Component)
      -[r:REVISED_BY]->(t:ChangeRecord)-[f:NAMES]->(j:Job)
WHERE all(scope IN [m.scope, n.scope, i.scope, c.scope, r.scope, t.scope, f.scope, j.scope]
          WHERE scope IN $allowed)
  AND n.recorded <= $known AND t.recorded <= $known
RETURN j.id AS job, n.id AS dependency_source, t.id AS rename_source
"""

RULE_AT = """
MATCH (r:Rule {state: 'accepted'})-[:APPLIES_TO]->(:Site {id: $site})
WHERE r.effective <= $effective AND r.recorded <= $known
RETURN r.id AS revision, r.hours AS hours
ORDER BY r.effective DESC, r.recorded DESC LIMIT 1
"""

ROUTE_PULSE = """
MATCH (r:Rule {id: $revision, state: 'accepted'})-[:APPLIES_TO]->(s:Site)
      <-[:RESPONSIBLE_FOR]-(role:Assignment)<-[:ASSIGNED_TO]-(a:Agent)
WHERE role.starts <= $day AND $day < role.ends AND r.recorded <= $day
MERGE (p:Pulse {id: $event})
ON CREATE SET p.state = 'pending'
MERGE (p)-[:ABOUT]->(r)
MERGE (p)-[:NOTIFIES]->(a)
RETURN p.id AS event, a.id AS recipient
"""


class RelateCompatibilityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if relate.__version__ != "1.2.0":
            raise RuntimeError(f"Expected Relate 1.2.0, got {relate.__version__}")

    def setUp(self):
        work = TemporaryDirectory(prefix="coherence-relate-")
        self.addCleanup(work.cleanup)
        self.store = str(Path(work.name) / "demo.rl")
        with relate.connect(self.store) as connection:
            connection.execute(SEED)

    def test_fresh_reader_resolves_distinct_partnerships_and_authorized_history(self):
        with relate.connect(self.store, read_only=True) as fresh:
            delivery = fresh.execute(BOOT_CONTEXT, {"agent": "delivery", "day": 14}).single()
            legal = fresh.execute(BOOT_CONTEXT, {"agent": "legal", "day": 14}).single()
        self.assertEqual(delivery, {
            "agent": "delivery", "principal": "maya", "role": "Delivery",
            "observation": "handoff-note", "author": "ari",
        })
        self.assertEqual(legal, {
            "agent": "legal", "principal": "kai", "role": "Legal",
            "observation": "legal-review", "author": "kai",
        })

    def test_ended_assignment_and_unknown_agent_return_no_context(self):
        with relate.connect(self.store, read_only=True) as fresh:
            prior = fresh.execute(BOOT_CONTEXT, {"agent": "former", "day": 9}).single()
            departed = fresh.execute(BOOT_CONTEXT, {"agent": "former", "day": 10}).data()
            missing = fresh.execute(BOOT_CONTEXT, {"agent": "unknown", "day": 10}).data()
        self.assertEqual(prior["principal"], "ari")
        self.assertEqual(departed, [])
        self.assertEqual(departed, missing)

    def test_dependency_requires_both_permitted_records(self):
        params = {"site": "north", "allowed": ["delivery"], "known": 14}
        with relate.connect(self.store) as connection:
            self.assertEqual(connection.execute(DEPENDENCY, params).data(), [
                {"job": "notify-8", "dependency_source": "dependency", "rename_source": "rename"},
            ])
            self.assertEqual(connection.execute(DEPENDENCY, {**params, "known": 12}).data(), [])
            self.assertEqual(connection.execute(DEPENDENCY, {**params, "allowed": ["legal"]}).data(), [])
            for record in ("dependency", "rename"):
                with self.subTest(restricted_record=record):
                    connection.execute(
                        "MATCH (w {id: $id}) SET w.scope = 'private'", {"id": record},
                    )
                    self.assertEqual(connection.execute(DEPENDENCY, params).data(), [])
                    connection.execute(
                        "MATCH (w {id: $id}) SET w.scope = 'delivery'", {"id": record},
                    )

    def test_late_amendment_separates_effective_and_recorded_time(self):
        cases = (
            ("north", 12, 12, {"revision": "base", "hours": 48}),
            ("north", 12, 14, {"revision": "north-v2", "hours": 24}),
            ("north", 9, 14, {"revision": "base", "hours": 48}),
            ("north", 14, 14, {"revision": "north-v2", "hours": 24}),
            ("south", 14, 14, {"revision": "base", "hours": 48}),
        )
        with relate.connect(self.store, read_only=True) as fresh:
            for site, effective, known, expected in cases:
                with self.subTest(site=site, effective=effective, known=known):
                    self.assertEqual(fresh.execute(RULE_AT, {
                        "site": site, "effective": effective, "known": known,
                    }).single(), expected)

    def test_pulse_routes_to_current_owner_and_survives_repeated_publication(self):
        params = {"revision": "north-v2", "day": 14, "event": "amendment-notice"}
        expected = {"event": "amendment-notice", "recipient": "delivery"}
        with relate.connect(self.store) as connection:
            for unavailable in (
                {**params, "day": 13, "event": "too-early"},
                {**params, "revision": "draft", "event": "unsigned"},
            ):
                self.assertEqual(connection.execute(ROUTE_PULSE, unavailable).data(), [])
            for _ in range(2):
                self.assertEqual(connection.execute(ROUTE_PULSE, params).single(), expected)
        with relate.connect(self.store, read_only=True) as fresh:
            total = fresh.execute("MATCH (p:Pulse) RETURN count(p) AS total").single()
            saved = fresh.execute("""
                MATCH (p:Pulse)-[:NOTIFIES]->(a:Agent), (p)-[:ABOUT]->(r:Rule)
                RETURN p.id AS event, p.state AS state, a.id AS recipient, r.id AS revision
            """).data()
        self.assertEqual(total, {"total": 1})
        self.assertEqual(saved, [{**expected, "state": "pending", "revision": "north-v2"}])

    def test_second_writer_is_refused_while_store_is_open(self):
        with relate.connect(self.store) as owner:
            with self.assertRaisesRegex(relate.OperationalError, "storage locked"):
                with relate.connect(self.store):
                    pass
            self.assertEqual(owner.execute("RETURN 1 AS alive").single(), {"alive": 1})

    def test_connection_rejects_calls_from_another_thread(self):
        with relate.connect(self.store) as owner, ThreadPoolExecutor(max_workers=1) as worker:
            attempt = worker.submit(owner.execute, "RETURN 1 AS alive")
            with self.assertRaises(relate.ProgrammingError) as caught:
                attempt.result(timeout=5)
            self.assertEqual(caught.exception.kind, "WrongThread")
            self.assertEqual(owner.execute("RETURN 1 AS alive").single(), {"alive": 1})


if __name__ == "__main__":
    unittest.main()
