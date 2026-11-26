"""Temporal observation and Commercial Ops watch for the fictional North case."""

from argparse import ArgumentParser
from datetime import date, datetime, time, timedelta, timezone

from pathlib import Path

import relate

from demo_store import Gateway, SEED, SOURCES, Source


DEFAULT_QUESTION = "What changed for North, which job do we update, and who can approve it?"
START = date(2026, 11, 1)
DEMO_DAYS = (13, 14)
WATCHER = "commercial-ops"
DEFAULT_STORE = Path(__file__).resolve().parent / "data" / "north.rl"

NORTH_SOURCES = {
    **SOURCES,
    "north-register": Source(
        "Legal", 1, ("Delivery", "Commercial Ops"),
        "The existing critical notice deadline is 48 hours for North and South.",
        "notice-register",
    ),
    "change-approval": Source(
        "Operations", 9, ("Delivery",),
        "Stan in Operations approves changes to scheduler jobs. Delivery can propose a change.",
        "scheduler-approval",
    ),
}
SOURCE_IDS = (
    "north-register", "handoff-note", "scheduler-change", "change-approval",
    "north-amendment", "unsigned-draft", "private-note",
)
CONTRACT_REVISIONS = {
    "north-register": ("base", 48),
    "north-amendment": ("north-v2", 24),
}

WRITE_OBSERVATION = """
MATCH (s:Site {id:'north'})
MERGE (d:Day {date:$recorded_day})
MERGE (e:Day {date:$event_day})
MERGE (v:SourceVersion {id:$source_version})
ON CREATE SET v.source = $source, v.version = $version, v.span = $span
MERGE (o:Observation {id:$observation})
ON CREATE SET o.kind = $kind, o.statement = $statement, o.author = $author,
              o.recorded_at = $recorded_at, o.event_date = $event_day,
              o.effective_from = $effective_day, o.hours = $hours, o.scope = $scope
MERGE (s)-[:HAS_OBSERVATION]->(o)
MERGE (o)-[:RECORDED_ON]->(d)
MERGE (o)-[:HAPPENED_ON]->(e)
MERGE (o)-[:EVIDENCED_BY]->(v)
"""

VISIBLE_RULE = """
MATCH (:Site {id:'north'})-[:HAS_OBSERVATION]->(o:Observation {kind:'rule'})
      -[:EVIDENCED_BY]->(v:SourceVersion)
WHERE o.scope = $role AND v.source IN $sources
  AND o.recorded_at <= $known AND o.effective_from <= $effective
RETURN o.id AS observation, o.hours AS hours, o.event_date AS happened_on,
       o.recorded_at AS recorded_at, o.effective_from AS effective_from, v.source AS source
ORDER BY o.effective_from DESC, o.recorded_at DESC LIMIT 1
"""

VISIBLE_PATH = """
MATCH (:Site {id:'north'})-[:HAS_OBSERVATION]->(h:Observation {kind:'handoff'})
      -[:IDENTIFIES]->(c:Component)<-[:UPDATES]-(r:Observation {kind:'rename'})
      -[:NAMES]->(j:Job),
      (h)-[:EVIDENCED_BY]->(a:SourceVersion), (r)-[:EVIDENCED_BY]->(b:SourceVersion)
WHERE h.scope = $role AND r.scope = $role AND c.scope = 'delivery' AND j.scope = 'delivery'
  AND h.recorded_at <= $known AND r.recorded_at <= $known
  AND a.source IN $sources AND b.source IN $sources
RETURN c.id AS component, j.id AS job, [h.id, r.id] AS observations,
       [a.source, b.source] AS sources
LIMIT 2
"""


def calendar(day):
    return START + timedelta(days=day - 1)


def clock(day, at):
    return datetime.combine(calendar(day), at, timezone.utc)


def visible_sources(actor, day):
    return [
        NORTH_SOURCES[key].view(key)
        for key in SOURCE_IDS
        if actor.role in NORTH_SOURCES[key].audience and NORTH_SOURCES[key].recorded <= day
    ]


def write_observation(graph, key, kind, statement, event_day, *, effective_day=None, hours=None,
                      scope="Delivery", recorded_time=time(8)):
    source = NORTH_SOURCES[key]
    graph.execute(WRITE_OBSERVATION, {
        **source.view(key),
        "source_version": f"{key}:1:{source.anchor}", "observation": f"obs:{key}:1",
        "kind": kind, "statement": statement, "scope": scope,
        "event_day": calendar(event_day), "recorded_day": calendar(source.recorded),
        "recorded_at": clock(source.recorded, recorded_time),
        "effective_day": calendar(effective_day) if effective_day is not None else None,
        "hours": hours,
    })


def seed_north(graph):
    graph.execute(SEED)
    graph.execute("""
        CREATE (agent:Actor:Agent {id:'commercial-ops'}), (team:Team {name:'Commercial Ops'}),
               (routine:Routine {id:'signed-contract-watch', cadence:'daily', hour:10})
        CREATE (agent)-[:SERVES]->(team), (routine)-[:RUNS_AS]->(agent)
    """)
    write_observation(graph, "north-register", "rule", "North has a 48-hour notice deadline.",
                      1, effective_day=1, hours=48)
    write_observation(graph, "handoff-note", "handoff",
                      "Ari mapped North critical notices to the north-critical component.", 9)
    write_observation(graph, "scheduler-change", "rename",
                      "Operations renamed the job for north-critical to notify-8.", 13)
    write_observation(graph, "private-note", "rename", "Unverified personal job note.", 13,
                      scope="Former")
    graph.execute("""
        MATCH (h:Observation {id:'obs:handoff-note:1'}),
              (r:Observation {id:'obs:scheduler-change:1'}),
              (p:Observation {id:'obs:private-note:1'}),
              (c:Component {id:'north-critical'}), (j:Job {id:'notify-8'}),
              (other:Job {id:'notify-9'})
        CREATE (h)-[:IDENTIFIES]->(c), (r)-[:UPDATES]->(c), (r)-[:NAMES]->(j),
               (p)-[:UPDATES]->(c), (p)-[:NAMES]->(other)
    """)


def run_commercial_watch(graph, day):
    """Run one scheduled occurrence on the simulation clock."""
    gateway = Gateway(graph, day)
    accepted = gateway.rule("north", day, day)
    key = accepted["source"]
    source = NORTH_SOURCES.get(key)
    found = source is not None and source.recorded == day and key in CONTRACT_REVISIONS
    maya = gateway.bind("delivery")
    if found and maya.role not in source.audience:
        raise RuntimeError("Delivery has no grant for the scheduled finding.")

    when = clock(day, time(10))
    watch_id = f"signed-contract-watch:{when.isoformat()}"
    graph.autocommit = False
    try:
        graph.execute("""
            MATCH (routine:Routine {id:'signed-contract-watch'})-[:RUNS_AS]->(agent:Agent {id:$agent})
            MERGE (run:WatchRun {id:$id})
            ON CREATE SET run.scheduled_at = $when, run.status = $status
            MERGE (routine)-[:TRIGGERED]->(run)
            MERGE (agent)-[:RAN]->(run)
        """, {"id": watch_id, "when": when, "agent": WATCHER,
              "status": "amendment_found" if found else "no_new_amendment"})
        if found:
            revision, hours = CONTRACT_REVISIONS[key]
            if (revision, hours) != (accepted["revision"], accepted["hours"]):
                raise RuntimeError("The accepted rule disagrees with the contract register.")
            write_observation(
                graph, key, "rule", "Signed North amendment changes the deadline to 24 hours.",
                day, effective_day=accepted["effective_day"], hours=hours, recorded_time=when.time(),
            )
            graph.execute("""
                MATCH (run:WatchRun {id:$id}), (new:Observation {id:$observation}),
                      (old:Observation {id:'obs:north-register:1'}),
                      (recipient:Agent {id:$recipient})
                MERGE (new)-[:SUPERSEDES {site:'north'}]->(old)
                MERGE (run)-[:SURFACED]->(new)
                MERGE (run)-[:NOTIFIED]->(recipient)
            """, {"id": watch_id, "observation": f"obs:{key}:1", "recipient": maya.key})
        graph.commit()
    except Exception:
        graph.rollback()
        raise
    finally:
        graph.autocommit = True


def read_snapshot(graph, day, effective_day=None):
    """Build both inputs from one fresh Maya session and one source cutoff."""
    gateway = Gateway(graph, day)
    maya = gateway.bind("delivery")
    context = gateway.context(maya)
    sources = visible_sources(maya, day)
    params = {
        "known": clock(day, time.max), "effective": calendar(effective_day or day),
        "role": maya.role, "sources": [source["source"] for source in sources],
    }
    rule = graph.execute(VISIBLE_RULE, params).single().data()
    paths = graph.execute(VISIBLE_PATH, params).data()
    activity = graph.execute("""
        MATCH (:Agent {id:$watcher})-[:RAN]->(run:WatchRun)
        WHERE run.scheduled_at <= $known
        OPTIONAL MATCH (run)-[:NOTIFIED]->(:Agent {id:$maya}),
                       (run)-[:SURFACED]->(o:Observation {scope:$role})-[:EVIDENCED_BY]->(v:SourceVersion)
        WHERE o.recorded_at <= $known AND v.source IN $sources
        RETURN run.scheduled_at AS scheduled_at, v.source AS source,
               o.id AS observation, o.statement AS statement
        ORDER BY run.scheduled_at
    """, {**params, "watcher": WATCHER, "maya": maya.key}).data()
    observations = graph.execute("""
        MATCH (:Site {id:'north'})-[:HAS_OBSERVATION]->(o:Observation {scope:$role})
              -[:EVIDENCED_BY]->(v:SourceVersion),
              (o)-[:RECORDED_ON]->(d:Day), (o)-[:HAPPENED_ON]->(e:Day)
        WHERE o.recorded_at <= $known AND v.source IN $sources
        RETURN o.id AS id, o.kind AS kind, o.statement AS statement, o.author AS author,
               v.source AS source, v.version AS version, v.span AS span, d.date AS recorded_on,
               e.date AS happened_on, o.effective_from AS effective_from
        ORDER BY o.recorded_at, o.id
    """, params).data()
    return {
        "actor": context["principal"], "role": context["role"], "agent": context["agent"],
        "day": day, "effective_day": effective_day or day, "sources": sources,
        "relate": {"rule": rule, "dependency": paths[0] if len(paths) == 1 else None,
                   "activity": activity, "observations": observations},
    }


def create_north_store(path):
    with relate.connect(str(path)) as graph:
        seed_north(graph)
        for day in DEMO_DAYS:
            run_commercial_watch(graph, day)


def main():
    parser = ArgumentParser(description="Build the fictional North graph in a new single file.")
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.output.suffix != ".rl" or args.output.exists():
        parser.error("Choose a new filename ending in .rl.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    create_north_store(args.output)
    print(f"Created {args.output}")


if __name__ == "__main__":
    main()
