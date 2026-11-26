"""Relate gateway and independent simulator for the fictional handoff."""

import sqlite3
from contextlib import closing
from dataclasses import dataclass
from uuid import uuid4


class Denied(ValueError):
    """The actor or evidence is unavailable for the requested operation."""


@dataclass(frozen=True)
class Actor:
    key: str
    principal: str
    role: str
    session: str


@dataclass(frozen=True)
class Source:
    author: str
    recorded: int
    audience: tuple[str, ...]
    passage: str
    anchor: str

    def view(self, key):
        return {
            "source": key, "version": 1, "span": self.anchor,
            "author": self.author, "recorded_day": self.recorded,
            "passage": self.passage,
        }


SOURCES = {
    "north-amendment": Source(
        "Kai", 14, ("Legal", "Delivery"),
        "Signed amendment. North critical notices are due within 24 hours. "
        "Effective day 10. South and monthly reports keep their existing terms.",
        "clause-2",
    ),
    "unsigned-draft": Source(
        "Commercial", 13, ("Legal",),
        "Unsigned draft. Consider extending the change to both sites.", "clause-2",
    ),
    "handoff-note": Source(
        "Ari", 9, ("Delivery",),
        "North critical notices run on component north-critical. "
        "Find its current job in the scheduler change log.", "paragraph-1",
    ),
    "scheduler-change": Source(
        "Operations", 13, ("Delivery",),
        "Component north-critical now runs under scheduler job notify-8.",
        "change-41",
    ),
    "private-note": Source(
        "Ari", 13, ("Former",),
        "Unverified personal notes cite a different job.", "paragraph-1",
    ),
    "delivery-shift-17": Source(
        "Maya", 11, ("Product",),
        "Dispatch checked the shared inbox and called the site twice to learn whether "
        "North had acknowledged a critical notice. Acknowledgment status was unavailable.",
        "shift-note-17",
    ),
    "delivery-shift-forward": Source(
        "Customer Success", 12, ("Product",),
        "Forward of Maya's shift note 17 about manual checks for the same North notice.",
        "forward-4",
    ),
    "customer-ticket-51": Source(
        "Rosa", 15, ("Product",),
        "On a later North notice, the customer opened a support ticket to ask whether "
        "their acknowledgment reached Delivery. The portal did not show it.",
        "ticket-51",
    ),
    "ack-alert-spec": Source(
        "Noor", 13, ("Product",),
        "The pilot acknowledgment alert can report a receipt when the site connector "
        "emits an acknowledgment event. North's connector compatibility is unverified.",
        "pilot-spec-3",
    ),
    "customer-private": Source(
        "Rosa", 15, ("Customer Success",),
        "Separate customer correspondence outside the internal Product grant.",
        "private-2",
    ),
}

SEED = """
CREATE (delivery:Actor:Agent {id:'delivery'}), (maya:Person {name:'Maya'}),
       (legal:Actor:Agent {id:'legal'}), (kai:Person {name:'Kai'}),
       (operations:Actor:Operator {id:'operations'}), (stan:Person {name:'Stan'}),
       (former:Actor:Agent {id:'former'}), (ari:Person {name:'Ari'}),
       (product:Actor:Agent {id:'product'}), (noor:Person {name:'Noor'}),
       (dr:Assignment {role:'Delivery', start:10, stop:999}),
       (lr:Assignment {role:'Legal', start:1, stop:999}),
       (orr:Assignment {role:'Operations', start:1, stop:999}),
       (fr:Assignment {role:'Delivery', start:1, stop:10}),
       (pr:Assignment {role:'Product', start:1, stop:999}),
       (delivery)-[:SERVES]->(maya), (delivery)-[:ASSIGNED_TO]->(dr),
       (legal)-[:SERVES]->(kai), (legal)-[:ASSIGNED_TO]->(lr),
       (operations)-[:SERVES]->(stan), (operations)-[:ASSIGNED_TO]->(orr),
       (former)-[:SERVES]->(ari), (former)-[:ASSIGNED_TO]->(fr),
       (product)-[:SERVES]->(noor), (product)-[:ASSIGNED_TO]->(pr),
       (north:Site {id:'north'}), (south:Site {id:'south'}),
       (dr)-[:RESPONSIBLE_FOR]->(north), (fr)-[:RESPONSIBLE_FOR]->(north),
       (handoff:Work {id:'north-handoff', task:'Resolve the North critical notice handoff',
                     history:'Ari left a note on the dependency', grant:'institutional',
                     state:'open'}),
       (dr)-[:MAY_READ]->(handoff), (pr)-[:MAY_READ]->(handoff),
       (handoff)-[:ATTRIBUTED_TO]->(ari),
       (base:Rule {id:'base', hours:48, effective:1, recorded:1, status:'accepted'}),
       (amend:Rule {id:'north-v2', hours:24, effective:10, recorded:14,
                    status:'accepted', source:'north-amendment'}),
       (draft:Rule {id:'draft', hours:12, effective:13, recorded:13,
                    status:'unsigned', source:'unsigned-draft'}),
       (base)-[:APPLIES_TO]->(north), (base)-[:APPLIES_TO]->(south),
       (amend)-[:APPLIES_TO]->(north), (draft)-[:APPLIES_TO]->(north),
       (draft)-[:APPLIES_TO]->(south),
       (note:Evidence {id:'handoff-note', scope:'delivery', recorded:9}),
       (component:Component {id:'north-critical', scope:'delivery'}),
       (change:Evidence {id:'scheduler-change', scope:'delivery', recorded:13}),
       (private:Evidence {id:'private-note', scope:'private', recorded:13}),
       (job:Job {id:'notify-8', scope:'delivery'}), (other:Job {id:'notify-9', scope:'delivery'}),
       (north)-[:MAPPED_BY {scope:'delivery'}]->(note),
       (note)-[:IDENTIFIES {scope:'delivery'}]->(component),
       (component)-[:REVISED_BY {scope:'delivery'}]->(change),
       (component)-[:REVISED_BY {scope:'delivery'}]->(private),
       (change)-[:NAMES {scope:'delivery'}]->(job),
       (private)-[:NAMES {scope:'delivery'}]->(other)
"""

ACTIVE = """
MATCH (a:Actor {id:$actor})-[:SERVES]->(p:Person),
      (a)-[:ASSIGNED_TO]->(r:Assignment)
WHERE r.start <= $day AND $day < r.stop
RETURN p.name AS principal, r.role AS role
"""

RULE_AT = """
MATCH (r:Rule {status:'accepted'})-[:APPLIES_TO]->(:Site {id:$site})
WHERE r.effective <= $effective AND r.recorded <= $known
RETURN r.id AS revision, r.hours AS hours, r.effective AS effective_day,
       r.recorded AS recorded_day, r.source AS source
ORDER BY r.effective DESC, r.recorded DESC LIMIT 1
"""

DEPENDENCY = """
MATCH (s:Site {id:$site})-[m:MAPPED_BY]->(n:Evidence)-[i:IDENTIFIES]->(c:Component)
      -[r:REVISED_BY]->(t:Evidence)-[f:NAMES]->(j:Job)
WHERE all(scope IN [m.scope,n.scope,i.scope,c.scope,r.scope,t.scope,f.scope,j.scope]
          WHERE scope = 'delivery')
  AND n.recorded <= $day AND t.recorded <= $day
  AND NOT n.id IN $withheld AND NOT t.id IN $withheld
RETURN j.id AS job, c.id AS component, n.id AS note, t.id AS change
LIMIT 2
"""

PUBLISH_PULSE = """
MATCH (r:Rule {id:$revision, status:'accepted'})-[:APPLIES_TO]->(s:Site {id:$site})
      <-[:RESPONSIBLE_FOR]-(a:Assignment)<-[:ASSIGNED_TO]-(recipient:Agent)
WHERE a.start <= $day AND $day < a.stop AND r.recorded <= $day AND r.effective <= $day
MERGE (p:Pulse {id:$event})
ON CREATE SET p.publisher = $actor
MERGE (p)-[:ABOUT]->(r)
MERGE (p)-[:NOTIFIES]->(recipient)
RETURN p.id AS event, recipient.id AS recipient, s.id AS site, r.id AS revision
"""


class Gateway:
    def __init__(self, graph, day=14, withheld=()):
        self.graph = graph
        self.day = day
        self.withheld = tuple(withheld)

    def bind(self, key):
        result = self.graph.execute(ACTIVE, {"actor": key, "day": self.day}).data()
        if len(result) != 1:
            raise Denied("actor unavailable")
        return Actor(key, **result[0], session=uuid4().hex)

    def require(self, actor, role):
        current = self.graph.execute(ACTIVE, {"actor": actor.key, "day": self.day}).data()
        if current != [{"principal": actor.principal, "role": role}] or actor.role != role:
            raise Denied("operation unavailable")

    def source(self, actor, key):
        self.require(actor, actor.role)
        source = SOURCES.get(key)
        if (source is None or actor.role not in source.audience
                or source.recorded > self.day or key in self.withheld):
            raise Denied("source unavailable")
        return source.view(key)

    def context(self, actor):
        self.require(actor, actor.role)
        work = self.graph.execute("""
            MATCH (:Agent {id:$actor})-[:ASSIGNED_TO]->(r:Assignment)
                  -[:MAY_READ]->(w:Work)-[:ATTRIBUTED_TO]->(p:Person)
            WHERE r.start <= $day AND $day < r.stop
            RETURN w.task AS task, w.history AS history, p.name AS author,
                   w.grant AS grant, w.state AS state
        """, {"actor": actor.key, "day": self.day}).data()
        return {
            "agent": actor.key, "principal": actor.principal, "role": actor.role,
            "session": actor.session, "work": work,
        }

    def rule(self, site, effective, known):
        return self.graph.execute(RULE_AT, {
            "site": site, "effective": effective, "known": known,
        }).single()

    def amendment(self, actor):
        self.require(actor, "Legal")
        rule = self.rule("north", self.day, self.day)
        if not rule["source"]:
            raise Denied("amendment unavailable")
        return {
            "current": {**rule, "signed": True},
            "source": self.source(actor, rule["source"]),
            "conflicting_draft": {**self.source(actor, "unsigned-draft"), "signed": False},
        }

    def publish(self, actor, revision):
        self.require(actor, "Legal")
        rule = self.amendment(actor)["current"]
        if rule["revision"] != revision:
            raise Denied("amendment unavailable")
        return self.graph.execute(PUBLISH_PULSE, {
            "revision": revision, "site": "north", "event": f"notice:{revision}",
            "actor": actor.key, "day": self.day,
        }).single()

    def pulse(self, actor):
        self.require(actor, "Delivery")
        result = self.graph.execute("""
            MATCH (p:Pulse)-[:NOTIFIES]->(:Agent {id:$actor}),
                  (p)-[:ABOUT]->(r:Rule)-[:APPLIES_TO]->(s:Site)
            RETURN p.id AS event, p.publisher AS publisher, s.id AS site,
                   r.id AS revision, r.hours AS hours
        """, {"actor": actor.key}).data()
        if len(result) != 1:
            raise Denied("pulse unavailable")
        return result[0]

    def job_path(self, actor, event):
        pulse = self.pulse(actor)
        if pulse["event"] != event:
            raise Denied("pulse unavailable")
        paths = self.graph.execute(DEPENDENCY, {
            "site": pulse["site"], "day": self.day, "withheld": list(self.withheld),
        }).data()
        if len(paths) != 1:
            return {"status": "unresolved"}
        path = paths[0]
        return {
            "status": "resolved", "job": path["job"], "component": path["component"],
            "note_source": path["note"], "rename_source": path["change"],
            "evidence": [self.source(actor, path["note"]), self.source(actor, path["change"])],
        }

    def propose(self, actor, event, job, evidence):
        path = self.job_path(actor, event)
        if path["status"] != "resolved":
            raise Denied("two permitted sources are required")
        required = {source["source"] for source in path["evidence"]}
        if job != path["job"] or len(evidence) != len(required) or set(evidence) != required:
            raise Denied("proposal does not match the permitted evidence")
        pulse = self.pulse(actor)
        return self.graph.execute("""
            MATCH (pulse:Pulse {id:$event})
            MERGE (p:Proposal {id:$id})
            ON CREATE SET p.job = $job, p.site = $site, p.revision = $revision,
                          p.hours = $hours, p.evidence = $evidence, p.actor = $actor,
                          p.session = $session, p.state = 'proposed'
            MERGE (pulse)-[:PRODUCED]->(p)
            RETURN p.id AS id, p.job AS job, p.site AS site, p.revision AS revision,
                   p.hours AS hours, p.evidence AS evidence, p.state AS state
        """, {
            **pulse, "id": f"repair:{event}", "job": job, "evidence": sorted(evidence),
            "actor": actor.key, "session": actor.session,
        }).single()

    def approve(self, actor, proposal, token):
        self.require(actor, "Operations")
        if token != approval_token(proposal):
            raise Denied("approval does not match the proposed change")
        current = self.rule(proposal["site"], self.day, self.day)
        if (proposal["revision"], proposal["hours"]) != (current["revision"], current["hours"]):
            raise Denied("proposal revision is stale")
        self.graph.autocommit = False
        try:
            effect = self.graph.execute("""
                MATCH (p:Proposal {id:$id, job:$job, site:$site, revision:$revision, hours:$hours})
                WHERE p.state IN ['proposed','approved']
                MERGE (p)-[:SCHEDULES]->(e:Effect {id:$effect})
                ON CREATE SET e.state = 'pending', e.approver = $principal
                SET p.state = 'approved'
                RETURN e.id AS id, p.id AS proposal, p.job AS job, p.site AS site,
                       p.hours AS hours, p.revision AS revision, e.state AS state,
                       e.approver AS approver
            """, {
                **proposal, "effect": f"effect:{proposal['id']}", "principal": actor.principal,
            }).single()
            self.graph.commit()
        except Exception:
            self.graph.rollback()
            raise
        finally:
            self.graph.autocommit = True
        return effect

    def dispatch(self, actor, effect, simulator):
        self.require(actor, "Operations")
        current = self.rule(effect["site"], self.day, self.day)
        if (effect["revision"], effect["hours"]) != (current["revision"], current["hours"]):
            raise Denied("approved revision is stale")
        rows = self.graph.execute("""
            MATCH (p:Proposal {id:$proposal, state:'approved'})-[:SCHEDULES]->(e:Effect {id:$id})
            WHERE p.job=$job AND p.site=$site AND p.hours=$hours AND p.revision=$revision
              AND e.approver=$principal AND e.state IN ['pending','verified']
            RETURN e.id AS id
        """, {**effect, "principal": actor.principal}).data()
        if len(rows) != 1:
            raise Denied("approved effect unavailable")
        apply_effect(simulator, effect)

    def acknowledge(self, effect, receipt):
        self.graph.execute("""
            MATCH (e:Effect {id:$id})<-[:SCHEDULES]-(p:Proposal)<-[:PRODUCED]-(:Pulse)
            MATCH (w:Work {id:'north-handoff'})
            SET e.state = 'verified', e.receipt = $receipt, w.state = 'verified'
        """, {"id": effect["id"], "receipt": receipt})


def approval_token(proposal):
    return f"APPROVE {proposal['job']} {proposal['revision']} {proposal['hours']}"


def seed_simulator(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript("""
            CREATE TABLE jobs (id TEXT PRIMARY KEY, site TEXT, kind TEXT, hours INTEGER);
            CREATE TABLE effects (id TEXT PRIMARY KEY, job TEXT, hours INTEGER);
            CREATE TABLE sites (id TEXT PRIMARY KEY, recipient TEXT);
            CREATE TABLE findings (id TEXT PRIMARY KEY, site TEXT, reported INTEGER);
            CREATE TABLE inbox (finding TEXT PRIMARY KEY, job TEXT, recipient TEXT, delivered INTEGER);
            INSERT INTO sites VALUES ('north','north-customer-inbox'), ('south','south-customer-inbox');
            INSERT INTO jobs VALUES ('notify-8','north','critical',48),
                                    ('notify-9','south','critical',48),
                                    ('monthly-north','north','routine',720),
                                    ('monthly-south','south','routine',720);
        """)


def apply_effect(path, effect):
    """Apply an approved job change once."""
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("BEGIN IMMEDIATE")
        inserted = db.execute(
            "INSERT OR IGNORE INTO effects VALUES (?, ?, ?)",
            (effect["id"], effect["job"], effect["hours"]),
        ).rowcount
        if not inserted:
            previous = db.execute(
                "SELECT job, hours FROM effects WHERE id=?", (effect["id"],),
            ).fetchone()
            if previous != (effect["job"], effect["hours"]):
                raise Denied("effect identifier already belongs to a different change")
            return
        updated = db.execute(
            "UPDATE jobs SET hours=? WHERE id=? AND site=? AND kind='critical'",
            (effect["hours"], effect["job"], effect["site"]),
        ).rowcount
        if updated != 1:
            raise Denied("scheduler target is outside the approved scope")


def advance_finding(path, finding, site, reported, through):
    """Place a finding on the timeline and deliver any notice due by the supplied tick."""
    if through < reported:
        raise ValueError("clock precedes finding")
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("INSERT OR IGNORE INTO findings VALUES (?, ?, ?)", (finding, site, reported))
        db.execute(
            """
            INSERT OR IGNORE INTO inbox
            SELECT f.id, j.id, s.recipient, f.reported + j.hours
            FROM findings f JOIN sites s ON f.site=s.id
            JOIN jobs j ON j.site=s.id AND j.kind='critical'
            WHERE f.id=? AND f.reported + j.hours <= ?
            """, (finding, through),
        )


def inspect_simulator(path):
    """Read actual persisted jobs and receipts through a separate connection."""
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.row_factory = sqlite3.Row
        return {
            "jobs": [dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY id")],
            "receipts": [dict(row) for row in db.execute("""
                SELECT i.finding, i.job, i.recipient, i.delivered - f.reported AS elapsed
                FROM inbox i JOIN findings f ON i.finding=f.id ORDER BY i.finding
            """)],
            "effect_count": db.execute("SELECT count(*) FROM effects").fetchone()[0],
        }


def verify_notice(before, after, effect):
    target = [job for job in before["jobs"] if job["site"] == "north" and job["kind"] == "critical"]
    if len(target) != 1 or target[0]["id"] != effect["job"] or target[0]["hours"] != 48:
        raise Denied("approved effect did not identify the original North job")
    expected = [
        {**job, "hours": 24} if job["id"] == target[0]["id"] else job for job in before["jobs"]
    ]
    receipts = after["receipts"]
    if after["jobs"] != expected or after["effect_count"] != 1 or len(receipts) != 1:
        raise Denied("scheduler state or receipt count did not match the walkthrough")
    receipt = receipts[0]
    if (receipt["finding"] != f"finding:{effect['id']}" or receipt["job"] != target[0]["id"]
            or receipt["recipient"] != "north-customer-inbox" or not 0 <= receipt["elapsed"] <= 24):
        raise Denied("notice receipt did not match the approved change")
    return receipt
