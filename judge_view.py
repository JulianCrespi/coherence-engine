"""Project verified replay results into scoped walkthrough views."""


def node(key, title, kind, x, y, detail, facts=()):
    return dict(id=key, title=title, kind=kind, x=x, y=y, detail=detail, facts=facts)


def edge(start, end, label, copy=False):
    return dict(start=start, end=end, label=label, copy=copy)


def source_node(key, title, x, y, record, extra=()):
    facts = (
        ("Author", record["author"]),
        ("Source", f"{record['source']} / {record['span']}"),
        ("Recorded", f"Day {record['recorded_day']}"),
    )
    return node(key, title, "Source", x, y, record["passage"], facts + extra)


def view(title, summary, focus, nodes, edges):
    return dict(title=title, summary=summary, focus=focus, nodes=nodes, edges=edges)


def build_views(trace):
    """Use only the payload available to each role or the separate verifier."""
    events = trace["events"]

    def event(name):
        return next(item for item in events if item["event"] == name)

    def tool(actor, name):
        return next(
            item["result"] for item in events
            if item.get("actor") == actor and item.get("tool") == name
        )

    restored = event("restored")
    delivery = restored["context"]
    work = delivery["work"][0]
    remember = view(
        "Maya’s agent remembers the handoff",
        "A fresh session reads the same partnership and Ari’s institutional note from Relate.",
        "delivery",
        [
            node("maya", delivery["principal"], "Person", 22, 23,
                 "Maya is the incoming lead for Delivery.", (("Role", delivery["role"]),)),
            node("prior", "Earlier session", "Session", 22, 69,
                 "This activation ended before the second context opened.",
                 (("Session", restored["prior_session"][:8]),)),
            node("delivery", "Delivery agent", "Agent", 50, 44,
                 "Relate restored the durable agent and its relationship to Maya.",
                 (("Stable agent", delivery["agent"]), ("Fresh session", delivery["session"][:8]))),
            node("work", "Open handoff", "Work", 78, 44, work["task"],
                 (("State at restart", work["state"]), ("Read grant", work["grant"]))),
            node("ari", work["author"], "Former lead", 78, 76, work["history"]),
        ],
        [edge("maya", "delivery", "works with"), edge("prior", "delivery", "fresh context"),
         edge("delivery", "work", "recovers"), edge("work", "ari", "attributed to")],
    )

    pulse = tool("delivery", "read_pulse")
    path = tool("delivery", "find_job")
    proposal = tool("delivery", "propose_repair")
    note, change = path["evidence"]
    respond = view(
        "One pulse, one proposed repair",
        "Delivery connects the original handoff note to a later rename to identify North’s current job.",
        "job",
        [
            node("pulse", "Legal pulse", "Pulse", 20, 23,
                 "The active Delivery assignment received the North amendment.",
                 (("Revision", pulse["revision"]), ("Window", f"{pulse['hours']} hours"))),
            node("delivery", "Delivery agent", "Agent", 48, 23,
                 "The agent read the pulse and both permitted source passages."),
            source_node("note", "Handoff note", 20, 68, note),
            source_node("change", "Scheduler rename", 47, 79, change),
            node("job", path["job"], "Scheduler job", 77, 55,
                 "Both records connect through the same component.",
                 (("Component", path["component"]), ("Site", proposal["site"].title()))),
            node("proposal", "Proposed repair", "Proposal", 78, 21,
                 "Delivery proposes the change for separate Operations approval.",
                 (("Notice window", f"{proposal['hours']} hours"), ("State", proposal["state"]))),
        ],
        [edge("pulse", "delivery", "received by"), edge("delivery", "job", "identifies"),
         edge("note", "job", "component"), edge("change", "job", "current name"),
         edge("job", "proposal", "target")],
    )

    legal = tool("legal", "read_context")
    amendment = tool("legal", "read_amendment")
    sent = tool("legal", "publish_pulse")
    clocks = event("amendment_clocks")
    signed = amendment["current"]
    legal_view = view(
        "Legal routes the signed change",
        "The signed amendment applies to North. The responsibility map routes it to Delivery.",
        "signed",
        [
            node("kai", legal["principal"], "Person", 19, 23,
                 "Kai is the Legal principal for this case."),
            node("legal", "Legal agent", "Agent", 46, 23,
                 "Legal reads the available amendment and publishes the accepted revision."),
            source_node("draft", "Unsigned draft", 19, 71, amendment["conflicting_draft"],
                        (("Disposition", "Unsigned"),)),
            source_node("signed", "Signed amendment", 48, 71, amendment["source"], (
                ("Revision", signed["revision"]),
                ("Effective", f"Day {signed['effective_day']}"),
                ("Known on effective day", f"{clocks['known_on_effective_day']['hours']} hours"),
            )),
            node("pulse", "Targeted pulse", "Pulse", 76, 46,
                 "Legal published one pulse for the current Delivery assignment.",
                 (("Event", sent["event"]), ("Recipient", sent["recipient"].title()))),
        ],
        [edge("kai", "legal", "works with"), edge("legal", "draft", "reviews", True),
         edge("legal", "signed", "reads"), edge("signed", "pulse", "triggers")],
    )

    approval = event("approved")["approval"]
    verified = event("verified_notice")
    receipt = verified["receipt"]
    before = {job["id"]: job for job in verified["before"]["jobs"]}
    after = {job["id"]: job for job in verified["after"]["jobs"]}
    target = after[approval["job"]]
    stable = tuple(
        (job["id"], f"{job['hours']} hours") for job in after.values()
        if job["id"] != target["id"] and job == before[job["id"]]
    )
    verifier = view(
        "The inbox confirms delivery",
        "The independent simulator read found one notice. South and the routine jobs kept their settings.",
        "receipt",
        [
            node("owner", approval["approver"], "Operations", 18, 24,
                 "The recorded Operations approval applies to this synthetic change."),
            node("approved", "Approved change", "Approval", 44, 24,
                 "The gateway accepted this exact revision, target, and window.",
                 (("Target", target["id"]), ("Revision", approval["revision"]))),
            node("target", target["id"], "Scheduler job", 75, 24,
                 "The independent scheduler read confirms the North job’s new configuration.",
                 (("Previous", f"{before[target['id']]['hours']} hours"),
                  ("Verified", f"{target['hours']} hours"))),
            node("unchanged", "Unaffected jobs", "Controls", 31, 72,
                 "The separate scheduler read returned these original settings.", stable),
            node("receipt", "North inbox", "Receipt", 75, 72,
                 "The simulated recipient inbox recorded the notice at the scheduled time.",
                 (("Recipient", receipt["recipient"]), ("Elapsed", f"{receipt['elapsed']} hours"))),
        ],
        [edge("owner", "approved", "authorizes"), edge("approved", "target", "updates"),
         edge("target", "receipt", "delivers"), edge("target", "unchanged", "checked together", True)],
    )

    product = tool("product", "read_context")
    signals = tool("product", "review_signals")
    work_note = next(item for item in signals["independent"] if item["team"] == "Delivery")
    customer_note = next(item for item in signals["independent"] if item["team"] == "Customer Success")
    capability = tool("product", "review_capability")
    retained = event("discovery_retained")
    trial = retained["trial"]
    handoff = retained["handoff"]
    product_agent = node(
        "product", "Product agent", "Agent", 49, 48,
        f"{product['principal']}’s fresh session recovered two records from Relate.",
    )
    product_agent["readback"] = [
        dict(title=f"{handoff['state'].title()} North handoff",
             detail=f"{handoff['author']} left the dependency note for North’s critical notices."),
        dict(title="Pending one-site trial",
             detail=f"The proposal covers the acknowledgment alert at {trial['site'].title()}.",
             facts=(("Owner", trial["owner"]), ("Open question", trial["question"]))),
    ]
    discover = view(
        "Product connects evidence across teams",
        "Two independent reports point to an acknowledgment gap. A limited alert pilot offers a test.",
        "product",
        [
            source_node("shift", "Delivery shift note", 19, 27, work_note,
                        (("Origin", work_note["origin"]),)),
            source_node("ticket", "Customer Success ticket", 19, 60, customer_note,
                        (("Origin", customer_note["origin"]),)),
            source_node("copy", "Forwarded shift note", 49, 82, signals["copies"][0],
                        (("Origin", signals["copies"][0]["origin"]),)),
            product_agent,
            source_node("pilot", "Alert pilot", 77, 24, capability["evidence"],
                        (("Readiness", capability["readiness"].title()),)),
            node("trial", "One-site trial", "Proposal", 77, 69, trial["next_step"],
                 (("Owner", trial["owner"]), ("Site", trial["site"].title()),
                  ("Open question", trial["question"]),
                  ("State", trial["status"].replace("-", " ").capitalize()))),
        ],
        [edge("copy", "shift", "same origin", True), edge("shift", "product", "evidence"),
         edge("ticket", "product", "evidence"), edge("product", "trial", "proposes"),
         edge("pilot", "trial", "to test")],
    )

    return {
        ("remember", "delivery"): remember,
        ("respond", "delivery"): respond,
        ("respond", "legal"): legal_view,
        ("respond", "verifier"): verifier,
        ("discover", "product"): discover,
    }
