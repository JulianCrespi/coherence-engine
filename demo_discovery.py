"""Bounded Product discovery in the handoff's Relate store."""

from demo_store import Denied, Gateway


SEED_DISCOVERY = """
MATCH (:Actor {id:'product'})-[:ASSIGNED_TO]->(r:Assignment {role:'Product'}),
      (site:Site {id:'north'})
CREATE (w:Workflow {id:'notice-acknowledgment', scope:'product'}),
       (w)-[:AT]->(site), (r)-[:REVIEWS {scope:'product'}]->(w),
       (first:Origin {id:'shift-17', scope:'product'}),
       (second:Origin {id:'support-51', scope:'product'}),
       (hidden:Origin {id:'private-2', scope:'private'}),
       (delivery:Signal {source:'delivery-shift-17', team:'Delivery',
                         scope:'product', recorded:11, copy:false}),
       (forward:Signal {source:'delivery-shift-forward', team:'Customer Success',
                        scope:'product', recorded:12, copy:true}),
       (customer:Signal {source:'customer-ticket-51', team:'Customer Success',
                         scope:'product', recorded:15, copy:false}),
       (private:Signal {source:'customer-private', team:'Customer Success',
                        scope:'private', recorded:15, copy:false}),
       (delivery)-[:FROM_EVENT {scope:'product'}]->(first),
       (forward)-[:FROM_EVENT {scope:'product'}]->(first),
       (customer)-[:FROM_EVENT {scope:'product'}]->(second),
       (private)-[:FROM_EVENT {scope:'private'}]->(hidden),
       (delivery)-[:OBSERVES {scope:'product'}]->(w),
       (forward)-[:OBSERVES {scope:'product'}]->(w),
       (customer)-[:OBSERVES {scope:'product'}]->(w),
       (private)-[:OBSERVES {scope:'private'}]->(w),
       (cap:Capability {id:'acknowledgment-alert', source:'ack-alert-spec',
                        scope:'product', readiness:'pilot', recorded:13}),
       (cap)-[:SUPPORTS {scope:'product'}]->(w)
"""

PRODUCT_SCOPE = """
MATCH (:Actor {id:$actor})-[:ASSIGNED_TO]->(r:Assignment {role:'Product'})
      -[:REVIEWS {scope:'product'}]->(w:Workflow {scope:'product'})-[:AT]->(s:Site)
WHERE r.start <= $day AND $day < r.stop
"""


class Discovery(Gateway):
    def signals(self, actor):
        self.require(actor, "Product")
        rows = self.graph.execute(PRODUCT_SCOPE + """
            MATCH (n:Signal {scope:'product'})-[:OBSERVES {scope:'product'}]->(w),
                  (n)-[:FROM_EVENT {scope:'product'}]->(event:Origin {scope:'product'})
            WHERE n.recorded <= $day AND NOT n.source IN $withheld
            RETURN event.id AS origin, n.source AS source, n.team AS team, n.copy AS copy
            ORDER BY n.recorded, n.source LIMIT 9
        """, {"actor": actor.key, "day": self.day, "withheld": list(self.withheld)}).data()
        if len(rows) > 8:
            raise Denied("discovery evidence exceeds the walkthrough limit")
        independent = {}
        copies = []
        for row in rows:
            view = {**self.source(actor, row["source"]), "team": row["team"], "origin": row["origin"]}
            if row["copy"]:
                copies.append(view)
            else:
                independent.setdefault(row["origin"], view)
        return {"independent": list(independent.values()), "copies": copies}

    def capability(self, actor):
        self.require(actor, "Product")
        rows = self.graph.execute(PRODUCT_SCOPE + """
            MATCH (c:Capability {scope:'product'})-[:SUPPORTS {scope:'product'}]->(w)
            WHERE c.recorded <= $day AND NOT c.source IN $withheld
            RETURN c.id AS capability, s.id AS site, c.readiness AS readiness, c.source AS source
            LIMIT 2
        """, {"actor": actor.key, "day": self.day, "withheld": list(self.withheld)}).data()
        if len(rows) != 1:
            raise Denied("one scoped candidate capability is required")
        row = rows[0]
        return {**row, "evidence": self.source(actor, row["source"])}

    def save_trial(self, actor, delivery_source, customer_source, capability, next_step, question):
        available = self.signals(actor)["independent"]
        allowed = {row["source"]: row["team"] for row in available}
        if allowed.get(delivery_source) != "Delivery" or allowed.get(customer_source) != "Customer Success":
            raise Denied("trial requires independent Delivery and Customer Success sources")
        candidate = self.capability(actor)
        if candidate["capability"] != capability or candidate["readiness"] != "pilot":
            raise Denied("trial requires a permitted pilot capability")
        if not (0 < len(next_step.strip()) <= 220 and 0 < len(question.strip()) <= 220):
            raise Denied("trial requires a concise next step and compatibility question")
        rows = self.graph.execute(PRODUCT_SCOPE + """
            MATCH (d:Signal {source:$delivery})-[:OBSERVES]->(w),
                  (cs:Signal {source:$customer})-[:OBSERVES]->(w),
                  (c:Capability {id:$capability})-[:SUPPORTS]->(w)
            MERGE (t:Trial {id:$id})
            ON CREATE SET t.scope = 'product', t.owner = $owner, t.proposed_by = $actor,
                          t.session = $session, t.status = 'awaiting-review', t.recorded = $day,
                          t.delivery_source = $delivery, t.customer_source = $customer,
                          t.next_step = $step, t.compatibility_question = $question
            WITH t, w, d, cs, c
            WHERE t.delivery_source = $delivery AND t.customer_source = $customer
            MERGE (t)-[:FOR_WORKFLOW]->(w)
            MERGE (t)-[:SUPPORTED_BY]->(d)
            MERGE (t)-[:SUPPORTED_BY]->(cs)
            MERGE (t)-[:TESTS]->(c)
            RETURN t.id AS id
        """, {
            "actor": actor.key, "day": self.day, "owner": actor.principal,
            "session": actor.session, "delivery": delivery_source, "customer": customer_source,
            "capability": capability, "id": f"pilot:{candidate['site']}:{capability}",
            "step": next_step.strip(), "question": question.strip(),
        }).data()
        if len(rows) != 1:
            raise Denied("trial already has a different evidence basis")
        return rows[0]

    def retained(self, actor, trial):
        signals = {row["source"]: row for row in self.signals(actor)["independent"]}
        capability = self.capability(actor)
        rows = self.graph.execute(PRODUCT_SCOPE + """
            MATCH (t:Trial {id:$trial, scope:'product'})-[:FOR_WORKFLOW]->(w),
                  (t)-[:TESTS]->(c:Capability {id:$capability}),
                  (t)-[:SUPPORTED_BY]->(n:Signal {scope:'product'})-[:OBSERVES]->(w)
            RETURN t.owner AS owner, t.proposed_by AS author, t.session AS author_session,
                   t.status AS status, t.next_step AS next_step, t.compatibility_question AS question,
                   s.id AS site, t.recorded AS recorded_day, collect(DISTINCT n.source) AS sources
        """, {
            "actor": actor.key, "day": self.day, "trial": trial,
            "capability": capability["capability"],
        }).data()
        if len(rows) != 1 or len(rows[0]["sources"]) != 2 or not set(rows[0]["sources"]) <= signals.keys():
            raise Denied("trial unavailable")
        row = rows[0]
        return {
            "id": trial, **row, "capability": capability["capability"],
            "evidence": [signals[key] for key in sorted(row["sources"])] + [capability["evidence"]],
        }
