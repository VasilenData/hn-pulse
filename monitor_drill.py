"""A controlled local-publication outage; never modifies or stops the live site.

Default delivery uses a real local HTTP receiver. --email instead sends two
clearly labelled drill emails using the deployment's configured email adapter.
Provider acceptance is recorded separately from human inbox receipt.
"""
import argparse
import copy
import hashlib
import json
import tempfile
import threading
from datetime import timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import monitor_worker as worker


def run(output, use_email=False):
    output = Path(output)
    if output.exists():
        raise ValueError("Choose a new evidence filename; existing evidence is never overwritten")
    source = worker.ROOT / "docs/data.json"
    original = source.read_bytes()
    payload = json.loads(original)
    received = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = json.dumps(payload).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append({"received_at": worker.utcnow().isoformat(), "idempotency_key": self.headers.get("Idempotency-Key"),
                             "event": body})
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    source_url = f"http://127.0.0.1:{server.server_port}/data.json"
    send = worker.email_transport() if use_email else worker.WebhookTransport(
        f"http://127.0.0.1:{server.server_port}/notifications", allow_local=True)
    steps = []
    started = worker.utcnow()
    try:
        with tempfile.TemporaryDirectory(prefix="hn-monitor-drill-") as directory:
            path = Path(directory) / "drill.sqlite"
            for label, hours in (("healthy", 1), ("source_overdue", 7), ("same_incident", 7), ("recovered", 1)):
                now = worker.utcnow()
                payload["generated_at"] = (now - timedelta(minutes=2)).isoformat()
                payload["quality"]["newest_snapshot_at"] = (now - timedelta(hours=hours)).isoformat()
                observation = worker.observe(source_url, allow_local=True)
                # Reopen state between every check: state must survive the process/connection lifecycle.
                con = worker.connect(path)
                event = worker.record(con, observation, scope="controlled-drill")
                deliveries = worker.deliver(con, send)
                pending = con.execute("SELECT COUNT(*) FROM outbox WHERE delivered_at IS NULL").fetchone()[0]
                con.close()
                steps.append({"step": label, "observation": observation,
                              "transition": event["kind"] if event else None,
                              "deliveries": deliveries, "pending_notifications": pending})
            if [s["transition"] for s in steps] != [None, "alert", None, "recovery"]:
                raise AssertionError("unexpected incident transitions")
            if any(s["pending_notifications"] for s in steps):
                raise AssertionError("notification delivery not accepted; review deployment logs")
            if not use_email and [r["event"]["kind"] for r in received] != ["alert", "recovery"]:
                raise AssertionError("receiver did not receive exactly one alert and one recovery")
        if source.read_bytes() != original:
            raise AssertionError("committed export changed during drill")
        result = {"schema_version": 1, "scope": "controlled synthetic outage; live publication untouched",
                  "started_at": started.isoformat(), "completed_at": worker.utcnow().isoformat(),
                  "monitor_code_sha256": worker.fingerprint(), "fixture_sha256": hashlib.sha256(original).hexdigest(),
                  "transport": "configured_email" if use_email else "local_http_receiver",
                  "email_inbox_receipt_verified": False, "persistent_state_reopened_each_step": True,
                  "live_or_committed_export_modified": False, "steps": steps,
                  "received": copy.deepcopy(received),
                  "limits": ["Manual checks; does not measure the scheduled detection interval.",
                             "Provider acceptance does not establish inbox delivery or human acknowledgement.",
                             "No claim about real provider outages, long-term uptime, or source data loss."]}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--email", action="store_true", help="Send two labelled drill messages to ALERT_TO")
    args = parser.parse_args()
    result = run(args.output, args.email)
    print(json.dumps({"result": "passed", "transport": result["transport"], "output": str(args.output)}))
