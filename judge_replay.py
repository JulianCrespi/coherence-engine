"""Replay the recorded Coherence Engine tools against a fresh local store."""

import argparse
import hashlib
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlsplit

import relate

from demo import FIXTURE, Trace, run_demo, run_discovery
from demo_store import Denied, approval_token


ROOT = Path(__file__).resolve().parent
RECORDING = ROOT / "fixtures" / "live-walkthrough.json"
PORT = 8765
SESSION_KEYS = {"session", "prior_session", "author_session", "reader_session"}


class ReplayMismatch(ValueError):
    """The execution could not reproduce the captured walkthrough."""


def comparable(value):
    if isinstance(value, dict):
        return {key: comparable(item) for key, item in value.items() if key not in SESSION_KEYS}
    if isinstance(value, list):
        return [comparable(item) for item in value]
    return value


class RecordedModel:
    """Supply captured native calls in their original actor and session order."""

    def __init__(self, recording):
        self.calls = []
        self.sessions = {}
        self.position = 0
        native = None
        for event in recording["events"]:
            if event["event"] == "model_turn":
                native = event
            elif event["event"] == "tool":
                function = {"name": event["tool"], "arguments": event["arguments"]}
                if (
                    native is None
                    or (native["actor"], native["session"]) != (event["actor"], event["session"])
                    or len(native["tool_calls"]) != 1
                    or any(native["tool_calls"][0]["function"].get(k) != v for k, v in function.items())
                ):
                    raise ReplayMismatch("recorded tool is missing its native model request")
                self.calls.append(event)
                native = None
        if not self.calls:
            raise ReplayMismatch("recording contains no native requests")

    def arguments(self, session, spec, instruction):
        if self.position >= len(self.calls):
            raise ReplayMismatch("walkthrough requested an extra tool")
        call = self.calls[self.position]
        name = spec["function"]["name"]
        actor = session.actor
        if (call["actor"], call["tool"]) != (actor.key, name):
            raise ReplayMismatch(f"tool order changed at {actor.key}.{name}")
        recorded = call["session"]
        if recorded not in self.sessions:
            if actor.session in self.sessions.values():
                raise ReplayMismatch("distinct recorded sessions merged")
            self.sessions[recorded] = actor.session
        if self.sessions[recorded] != actor.session:
            raise ReplayMismatch("recorded session boundaries changed")
        self.position += 1
        return call["arguments"]


def replay(path=RECORDING, say=print):
    data = path.read_bytes()
    recorded = json.loads(data)
    if (
        recorded["fixture"] != FIXTURE or recorded["mode"] != "live-local"
        or recorded["handoff_status"] != "verified" or recorded["status"] != "discovery_proposed"
    ):
        raise ReplayMismatch("expected a complete live handoff and discovery recording")
    model = RecordedModel(recorded)
    approved = [event["approval"] for event in recorded["events"] if event["event"] == "approved"]
    if len(approved) != 1:
        raise ReplayMismatch("expected one recorded Operations approval")

    def approve(proposal):
        for field in ("job", "site", "hours", "revision"):
            if proposal[field] != approved[0][field]:
                raise ReplayMismatch(f"recorded approval differs on {field}")
        if proposal["id"] != approved[0]["proposal"]:
            raise ReplayMismatch("recorded approval targets another proposal")
        say("Reapplying the recorded synthetic Operations approval.")
        return approval_token(proposal)

    trace = Trace("judge-replay", model=recorded["model"])
    trace.record["recording_sha256"] = hashlib.sha256(data).hexdigest()
    say("Judge replay. Recorded model calls, fresh Relate and simulator operations.")
    with TemporaryDirectory(prefix="coherence-judge-") as temp:
        work = Path(temp)
        trace.record["handoff_status"] = run_demo(work, model, trace, approve, say)
        if trace.record["handoff_status"] != recorded["handoff_status"]:
            raise ReplayMismatch("handoff result changed")
        trace.record["status"] = run_discovery(work, model, trace, say)
    if trace.record["status"] != recorded["status"] or model.position != len(model.calls):
        raise ReplayMismatch("discovery result or recorded tool count changed")

    expected = [event for event in recorded["events"] if event["event"] != "model_turn"]
    actual = trace.record["events"]
    if len(expected) != len(actual):
        raise ReplayMismatch("execution event count changed")
    for old, new in zip(expected, actual):
        if comparable(old) != comparable(new):
            raise ReplayMismatch(f"fresh read or effect changed at {old['event']} {old.get('tool', '')}")
    say(f"Verified replay. {model.position} recorded tool calls reproduced.")
    return trace.record


def create_server(views, port):
    assets = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/viewer.css": ("viewer.css", "text/css; charset=utf-8"),
        "/viewer.js": ("viewer.js", "text/javascript; charset=utf-8"),
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlsplit(self.path)
            if url.path == "/api/view":
                params = parse_qs(url.query)
                key = (params.get("scene", [""])[0], params.get("role", [""])[0])
                if key not in views:
                    self.send_error(404, "Unknown scene or role")
                    return
                payload = json.dumps(views[key], ensure_ascii=False).encode()
                content_type = "application/json; charset=utf-8"
            elif url.path in assets:
                name, content_type = assets[url.path]
                payload = (ROOT / "viewer" / name).read_bytes()
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; object-src 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(payload)

    return HTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording", type=Path, default=RECORDING)
    parser.add_argument("--trace", type=Path, help="Write a new verified replay trace.")
    parser.add_argument("--serve", action="store_true", help="Open a loopback judge view.")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    try:
        result = replay(args.recording, say=lambda line: print(line, flush=True))
        if args.trace:
            with args.trace.open("x", encoding="utf-8") as stream:
                json.dump(result, stream, indent=2)
                stream.write("\n")
        if args.serve:
            from judge_view import build_views

            with create_server(build_views(result), args.port) as server:
                print(f"Judge view at http://127.0.0.1:{server.server_port}", flush=True)
                server.serve_forever()
    except KeyboardInterrupt:
        return 0
    except (OSError, KeyError, ValueError, Denied, relate.Error) as error:
        print(f"Replay stopped. {error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
