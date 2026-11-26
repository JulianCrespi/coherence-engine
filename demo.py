"""Run the Coherence Engine walkthrough against a disposable Relate store."""

import argparse
import http.client
import json
from contextlib import closing, nullcontext
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import relate

from demo_discovery import Discovery, SEED_DISCOVERY
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


MODEL = "qwen3:1.7b"
MODEL_DIGEST = "8f68893c685c3ddff2aa3fffce2aa60a30bb2da65ca488b61fff134a4d1730e7"
PORT = 11435
FIXTURE = "north-handoff-v1"


def tool_spec(name, description, **properties):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
        },
    }


STRING = {"type": "string"}
TOOLS = {
    "read_context": tool_spec("read_context", "Restore your own agent and working context."),
    "read_amendment": tool_spec("read_amendment", "Read the current signed rule and draft."),
    "publish_pulse": tool_spec(
        "publish_pulse", "Publish a single pulse about the current signed revision.", revision=STRING,
    ),
    "read_pulse": tool_spec("read_pulse", "Read the pulse routed to you."),
    "find_job": tool_spec(
        "find_job", "Follow the pulse to a job and its two supporting sources.", event=STRING,
    ),
    "propose_repair": tool_spec(
        "propose_repair", "Propose a change to the resolved job for Operations to review.",
        event=STRING, job=STRING,
        note_source={"type": "string", "description": "Copy note_source from find_job."},
        rename_source={"type": "string", "description": "Copy rename_source from find_job."},
    ),
    "review_signals": tool_spec("review_signals", "Read Product's observations and their origins."),
    "review_capability": tool_spec("review_capability", "Read the relevant Product pilot capability."),
    "save_trial": tool_spec(
        "save_trial", "Record a one-site trial proposal for human Product review.",
        delivery_source=STRING, customer_source=STRING, capability=STRING,
        next_step={"type": "string", "description": "One short action before or during a pilot."},
        question={"type": "string", "description": "One unresolved compatibility question."},
    ),
}


def valid_arguments(spec, args):
    properties = spec["function"]["parameters"]["properties"]
    return (isinstance(args, dict) and set(args) == set(properties)
            and all(isinstance(value, str) and value for value in args.values()))


class Trace:
    def __init__(self, mode, model=None):
        self.record = {
            "fixture": FIXTURE, "mode": mode, "model": model, "events": [],
            "status": "in_progress",
        }

    def add(self, event, **data):
        self.record["events"].append({"event": event, **data})


class LocalModel:
    """Use the Ollama tool protocol over a literal loopback connection."""

    def __init__(self, port):
        self.port = port
        data = self.request("GET", "/api/tags")
        models = [model for model in data["models"] if model["name"] == MODEL]
        if len(models) != 1 or models[0]["digest"] != MODEL_DIGEST:
            raise Denied(f"the verified local {MODEL} model is unavailable")
        self.identity = {"name": MODEL, "digest": models[0]["digest"]}

    def request(self, method, path, value=None):
        with closing(http.client.HTTPConnection("127.0.0.1", self.port, timeout=40)) as connection:
            connection.request(
                method, path, None if value is None else json.dumps(value),
                {"Content-Type": "application/json"},
            )
            response = connection.getresponse()
            payload = response.read(512_001)
            if response.status != 200 or len(payload) > 512_000:
                raise Denied(f"local model request failed ({response.status})")
            return json.loads(payload)

    def arguments(self, session, spec, instruction):
        tool = spec["function"]
        name = tool["name"]
        keys = tool["parameters"]["required"]
        shape = f"Use exactly these argument keys: {', '.join(keys)}." if keys else (
            "Use the empty argument object {}."
        )
        instruction = f"{instruction} {shape}"
        session.messages.append({"role": "user", "content": instruction})
        for _ in range(2):
            response = self.request("POST", "/api/chat", {
                "model": MODEL, "messages": session.messages, "tools": [spec],
                "stream": False, "think": False,
                "options": {"temperature": 0, "num_ctx": 4096, "num_predict": 300},
            })
            message = response["message"]
            calls = message.get("tool_calls", [])
            session.trace.add(
                "model_turn", actor=session.actor.key, session=session.actor.session,
                instruction=instruction, content=message.get("content", ""), tool_calls=calls,
            )
            if len(calls) == 1:
                function = calls[0].get("function", {})
                args = function.get("arguments")
                if function.get("name") == name and valid_arguments(spec, args):
                    session.messages.append(message)
                    return args
            session.messages.append({
                "role": "user", "content": f"Call {name} once. {shape}",
            })
        raise Denied(f"{session.actor.role} did not request {name}")


class ScriptedModel:
    """Exercise the same tools with deterministic calls in the smoke run."""

    identity = None

    def arguments(self, session, spec, instruction):
        name = spec["function"]["name"]
        if name == "publish_pulse":
            return {"revision": session.results["read_amendment"]["current"]["revision"]}
        if name == "find_job":
            return {"event": session.results["read_pulse"]["event"]}
        if name == "propose_repair":
            path = session.results["find_job"]
            return {
                "event": session.results["read_pulse"]["event"], "job": path["job"],
                "note_source": path["note_source"], "rename_source": path["rename_source"],
            }
        if name == "save_trial":
            sources = {row["team"]: row["source"] for row in session.results["review_signals"]["independent"]}
            return {
                "delivery_source": sources["Delivery"], "customer_source": sources["Customer Success"],
                "capability": session.results["review_capability"]["capability"],
                "next_step": "Check North's connector before a one-site alert pilot.",
                "question": "Can North's site connector emit the acknowledgment event?",
            }
        return {}


class Session:
    def __init__(self, gateway, key, model, trace):
        self.actor = gateway.bind(key)
        self.model = model
        self.trace = trace
        self.results = {}
        self.messages = [{
            "role": "system",
            "content": "You are an agent in a fictional company. Use only available tools. "
                       "Ground every action in their returned records. Copy identifiers exactly.",
        }]
        actor = self.actor
        self.handlers = {"read_context": lambda: gateway.context(actor)}
        if actor.role == "Legal":
            self.handlers.update(
                read_amendment=lambda: gateway.amendment(actor),
                publish_pulse=lambda revision: gateway.publish(actor, revision),
            )
        elif actor.role == "Delivery":
            self.handlers.update(
                read_pulse=lambda: gateway.pulse(actor),
                find_job=lambda event: gateway.job_path(actor, event),
                propose_repair=lambda event, job, note_source, rename_source: gateway.propose(
                    actor, event, job, [note_source, rename_source],
                ),
            )
        elif actor.role == "Product":
            self.handlers.update(
                review_signals=lambda: gateway.signals(actor),
                review_capability=lambda: gateway.capability(actor),
                save_trial=lambda **args: gateway.save_trial(actor, **args),
            )

    def call(self, name, instruction):
        handler = self.handlers.get(name)
        if handler is None:
            raise Denied("operation unavailable")
        spec = TOOLS[name]
        args = self.model.arguments(self, spec, instruction)
        if not valid_arguments(spec, args):
            raise Denied(f"invalid arguments for {name}")
        result = handler(**args)
        self.results[name] = result
        self.messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result)})
        self.trace.add(
            "tool", actor=self.actor.key, session=self.actor.session,
            tool=name, arguments=args, result=result,
        )
        return result


def run_demo(work, model, trace, approve, say=print, withheld=()):
    graph_path = str(work / "handoff.rl")
    simulator_path = work / "scheduler.sqlite"
    seed_simulator(simulator_path)
    before = inspect_simulator(simulator_path)
    with relate.connect(graph_path) as graph:
        graph.execute(SEED)
        first = Session(Gateway(graph), "delivery", model, trace)
        previous = first.call("read_context", "Call read_context to identify your partnership.")
    say(f"Maya's Delivery agent ends session {previous['session'][:8]}.")

    with relate.connect(graph_path) as graph:
        gateway = Gateway(graph, withheld=withheld)
        delivery = Session(gateway, "delivery", model, trace)
        restored = delivery.call("read_context", "Call read_context to restore your partnership.")
        stable = ("agent", "principal", "role", "work")
        if (any(previous[key] != restored[key] for key in stable) or not restored["work"]
                or previous["session"] == restored["session"]):
            raise Denied("Delivery continuity did not survive the restart")
        note = restored["work"][0]
        say(f"Fresh session {restored['session'][:8]} remembers {restored['principal']} "
            f"and the open handoff from {note['author']} ({note['grant']} grant).")
        trace.add("restored", prior_session=previous["session"], context=restored)

        legal = Session(gateway, "legal", model, trace)
        legal.call("read_context", "Call read_context to identify your partnership.")
        amendment = legal.call("read_amendment", "Call read_amendment to inspect the signed record.")
        revision = amendment["current"]
        temporal = {
            "known_on_effective_day": gateway.rule("north", revision["effective_day"], 10),
            "read_after_recording": gateway.rule("north", revision["effective_day"], gateway.day),
        }
        trace.add("amendment_clocks", **temporal)
        say(f"Legal reads the signed {revision['hours']}-hour North rule "
            f"(effective day {revision['effective_day']}, recorded day {revision['recorded_day']}).")
        routed = legal.call(
            "publish_pulse", "Use publish_pulse with the signed current revision identifier. "
            "Copy only the revision field from current.",
        )
        pulse = delivery.call("read_pulse", "Call read_pulse to read your assigned notification.")
        if pulse["event"] != routed["event"] or routed["recipient"] != delivery.actor.key:
            raise Denied("pulse was not routed to the active Delivery agent")
        say(f"Relate routes a pulse from Legal to {restored['principal']}'s agent.")
        path = delivery.call(
            "find_job", "Use find_job with the event identifier returned by read_pulse.",
        )
        if path["status"] == "unresolved":
            after = inspect_simulator(simulator_path)
            if after != before:
                raise Denied("unresolved dependency changed the simulator")
            trace.add("unresolved", simulator=after)
            say("Delivery cannot establish the target. The simulator is untouched.")
            return "unresolved"
        for source in path["evidence"]:
            say(f"  {source['source']} · {source['span']} · {source['author']}")
            say(f"  {source['passage']}")
        proposal = delivery.call(
            "propose_repair", "Copy event from read_pulse. Copy job, note_source, "
            "and rename_source as strings from find_job.",
        )
        say(f"Delivery proposes {proposal['job']} → {proposal['hours']}h for {proposal['site'].title()}.")

        try:
            gateway.approve(delivery.actor, proposal, approval_token(proposal))
        except Denied:
            if (graph.execute("MATCH (e:Effect) RETURN count(e) AS count").single()["count"]
                    or inspect_simulator(simulator_path) != before):
                raise Denied("denied approval caused a side effect")
            trace.add("delivery_approval_denied", actor=delivery.actor.key)
        else:
            raise Denied("Delivery was allowed to approve its own repair")
        say("Delivery cannot approve the change. Operations owns that decision.")

        token = approve(proposal)
        if not token:
            trace.add("approval_pending", proposal=proposal["id"])
            return "approval_pending"
        operations = gateway.bind("operations")
        effect = gateway.approve(operations, proposal, token)
        trace.add("approved", approval=effect)
        gateway.dispatch(operations, effect, simulator_path)
        advance_finding(
            simulator_path, f"finding:{effect['id']}", effect["site"], reported=100, through=124,
        )
        after = inspect_simulator(simulator_path)
        receipt = verify_notice(before, after, effect)
        gateway.acknowledge(effect, receipt["finding"])
        trace.add("verified_notice", before=before, after=after, receipt=receipt)
    say(f"Verified in the simulated inbox. {receipt['recipient']} received "
        f"{receipt['job']} after {receipt['elapsed']}h.")
    say("South remains at 48h. Monthly schedules keep their original settings.")
    return "verified"


def run_discovery(work, model, trace, say=print, copied_only=False):
    graph_path = str(work / "handoff.rl")
    simulator_path = work / "scheduler.sqlite"
    before = inspect_simulator(simulator_path)
    withheld = ("customer-ticket-51",) if copied_only else ()
    trace.add("discovery_started", fixture="north-product-signals-v1", copied_only=copied_only)
    with relate.connect(graph_path) as graph:
        gateway = Discovery(graph, day=16, withheld=withheld)
        product = Session(gateway, "product", model, trace)
        context = product.call("read_context", "Call read_context to restore the Product partnership.")
        if len(context["work"]) != 1 or context["work"][0]["state"] != "verified":
            raise Denied("discovery needs the verified handoff")
        graph.execute(SEED_DISCOVERY)
        say(f"\nDream · Product agent for {context['principal']}")
        signals = product.call("review_signals", "Call review_signals to read the available observations.")
        for source in signals["independent"]:
            say(f"  {source['team']} · {source['source']} · {source['span']}")
            say(f"  {source['passage']}")
        for copy in signals["copies"]:
            say(f"  {copy['source']} is a copy of origin {copy['origin']}.")
        if not {"Delivery", "Customer Success"} <= {row["team"] for row in signals["independent"]}:
            trials = graph.execute("MATCH (t:Trial) RETURN count(t) AS count").single()["count"]
            if trials or inspect_simulator(simulator_path) != before:
                raise Denied("insufficient corroboration changed persisted state")
            trace.add("discovery_unresolved", reason="missing independent team evidence",
                      independent_origins=len(signals["independent"]), proposals=trials,
                      simulator_unchanged=True)
            say("Product lacks independent reports from both teams. No trial proposal was saved.")
            return "discovery_unresolved"
        candidate = product.call(
            "review_capability", "Call review_capability to inspect the pilot and its limit.",
        )
        say(f"  Product · {candidate['source']} · {candidate['evidence']['span']}")
        say(f"  {candidate['evidence']['passage']}")
        saved = product.call(
            "save_trial", "Copy the two independent source IDs as delivery_source and customer_source. "
            "Copy capability from review_capability. Suggest a one-site next_step and ask a "
            "short question about the open compatibility check.",
        )

    with relate.connect(graph_path, read_only=True) as graph:
        fresh = Discovery(graph, day=16, withheld=withheld)
        reviewer = fresh.bind("product")
        retained = fresh.retained(reviewer, saved["id"])
        lesson = fresh.context(reviewer)["work"][0]
    if (retained["author_session"] != product.actor.session
            or reviewer.session == product.actor.session
            or retained["owner"] != reviewer.principal or retained["status"] != "awaiting-review"
            or lesson["state"] != "verified" or inspect_simulator(simulator_path) != before):
        raise Denied("trial or handoff readback did not match the walkthrough")
    trace.add("discovery_retained", reader_session=reviewer.session, trial=retained,
              handoff=lesson, simulator_unchanged=True)
    say(f"Product proposes a one-site trial for {retained['owner']} at {retained['site'].title()}.")
    say(f"  Next step · {retained['next_step']}")
    say(f"  Open question · {retained['question']}")
    say("A fresh Product session reads the proposal and verified handoff from Relate.")
    return "discovery_proposed"


def prompt_approval(proposal):
    token = approval_token(proposal)
    try:
        return input(f"Operations (Stan), type {token} to apply the synthetic change.\n> ").strip()
    except EOFError:
        return ""


def probe_model(model, trace):
    probe = SimpleNamespace(
        actor=SimpleNamespace(key="probe", session="probe"), messages=[], trace=trace,
    )
    args = model.arguments(
        probe, tool_spec("echo", "Echo a synthetic test word.", word=STRING),
        "Call echo with the word ready.",
    )
    if args != {"word": "ready"}:
        raise Denied("native tool-call probe did not echo the test word")
    print(f"Native tool call passed on {MODEL}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scripted", action="store_true", help="Run a labeled smoke test.")
    parser.add_argument("--probe-model", action="store_true", help="Check a native local tool call.")
    parser.add_argument("--port", type=int, default=PORT, help="Local Ollama port.")
    parser.add_argument("--trace", type=Path, help="Write a new JSON trace without overwriting.")
    parser.add_argument("--withhold", choices=("handoff-note", "scheduler-change"))
    parser.add_argument("--discover", action="store_true", help="Continue to Product discovery.")
    parser.add_argument("--copied-only", action="store_true", help="Use the copied-only discovery control.")
    args = parser.parse_args()
    if args.probe_model and args.scripted:
        parser.error("--probe-model requires the live local model")
    if args.copied_only and not args.discover:
        parser.error("--copied-only requires --discover")
    if args.discover and (args.withhold or args.probe_model):
        parser.error("--discover requires the full handoff")

    try:
        trace_output = args.trace.open("x", encoding="utf-8") if args.trace else nullcontext()
    except OSError as error:
        parser.error(f"cannot create trace: {error}")
    with trace_output as output:
        trace = Trace("scripted-smoke" if args.scripted else "live-local")
        try:
            model = ScriptedModel() if args.scripted else LocalModel(args.port)
            trace.record["model"] = model.identity
            if args.probe_model:
                probe_model(model, trace)
                trace.record["status"] = "tool_probe_passed"
                return 0
            print(f"Coherence Engine · {trace.record['mode']} · fictional company")
            with TemporaryDirectory(prefix="coherence-demo-") as work:
                work = Path(work)
                trace.record["status"] = run_demo(
                    work, model, trace, prompt_approval,
                    withheld=(args.withhold,) if args.withhold else (),
                )
                if args.discover and trace.record["status"] == "verified":
                    trace.record["handoff_status"] = "verified"
                    trace.record["status"] = run_discovery(
                        work, model, trace, copied_only=args.copied_only,
                    )
            expected = "unresolved" if args.withhold else "verified"
            if args.discover:
                expected = "discovery_unresolved" if args.copied_only else "discovery_proposed"
            return 0 if trace.record["status"] == expected else 1
        except (Denied, OSError, ValueError, KeyError, http.client.HTTPException, relate.Error) as error:
            trace.record["status"] = "failed"
            trace.record["error"] = str(error)
            print(f"Run stopped. {error}")
            return 1
        finally:
            if output is not None:
                json.dump(trace.record, output, indent=2)
                output.write("\n")


if __name__ == "__main__":
    raise SystemExit(main())
