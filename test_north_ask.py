"""Check the temporal cutoffs and the two model inputs for the North slice."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import relate

from north_ask import prompt_for, run_pair
from north_memory import DEFAULT_QUESTION, DEFAULT_STORE, create_north_store, read_snapshot, run_commercial_watch


class NorthSliceTests(unittest.TestCase):
    def setUp(self):
        work = self.enterContext(TemporaryDirectory())
        path = Path(work) / "north.rl"
        create_north_store(path)
        self.graph = self.enterContext(relate.connect(str(path)))

    def test_packaged_graph_matches_the_fixture(self):
        with relate.connect(str(DEFAULT_STORE), read_only=True) as packaged:
            for day in (13, 14):
                self.assertEqual(read_snapshot(packaged, day), read_snapshot(self.graph, day))

    def test_knowledge_cutoff_and_effective_day_are_independent(self):
        early = read_snapshot(self.graph, 13, 12)
        later = read_snapshot(self.graph, 14, 12)
        before_effective_date = read_snapshot(self.graph, 14, 9)
        self.assertEqual(early["relate"]["rule"]["hours"], 48)
        self.assertEqual(later["relate"]["rule"]["hours"], 24)
        self.assertEqual(before_effective_date["relate"]["rule"]["hours"], 48)
        self.assertNotIn("north-amendment", {source["source"] for source in early["sources"]})
        self.assertIsNone(early["relate"]["activity"][0]["observation"])
        self.assertEqual([o["id"] for o in later["relate"]["observations"] if o["kind"] == "rule"],
                         ["obs:north-register:1", "obs:north-amendment:1"])

    def test_watch_records_one_linked_finding_on_retry(self):
        run_commercial_watch(self.graph, 14)
        run_commercial_watch(self.graph, 14)
        rows = self.graph.execute("""
            MATCH (:Team {name:'Commercial Ops'})<-[:SERVES]-(:Agent)-[:RAN]->(run:WatchRun)
                  -[:SURFACED]->(o:Observation)-[:SUPERSEDES]->(old:Observation),
                  (run)-[:NOTIFIED]->(:Agent {id:'delivery'})
            RETURN o.id AS current, old.id AS previous, count(run) AS count
        """).data()
        self.assertEqual(rows, [{"current": "obs:north-amendment:1",
                                 "previous": "obs:north-register:1", "count": 1}])

    def test_private_path_and_unsigned_source_are_excluded_from_both_arms(self):
        snapshot = read_snapshot(self.graph, 14)
        self.assertEqual(snapshot["actor"], "Maya")
        self.assertEqual(snapshot["relate"]["dependency"]["job"], "notify-8")
        for connected in (False, True):
            prompt = prompt_for(snapshot, DEFAULT_QUESTION, connected)
            for denied in ("private-note", "unsigned-draft", "notify-9"):
                self.assertNotIn(denied, prompt)

    def test_pair_has_one_shared_source_packet_and_only_relate_gets_the_graph(self):
        packets = []

        def capture(prompt, sources):
            packet = json.loads(prompt.split("\n\n", 1)[1])
            self.assertEqual(sources, [s["source"] for s in packet["context"]["sources"]])
            packets.append(packet)
            return {"answer": "captured"}

        snapshot = read_snapshot(self.graph, 14)
        result = run_pair(snapshot, DEFAULT_QUESTION, capture)
        self.assertEqual(result["model"], "gpt-6.2-sol")
        self.assertEqual(result["effort"], "low")
        self.assertEqual(len(packets), 2)
        baseline, connected = sorted(packets, key=lambda p: "relate" in p["context"])
        self.assertEqual(connected["context"].pop("relate")["rule"]["hours"], 24)
        self.assertEqual(baseline, connected)


if __name__ == "__main__":
    unittest.main()
