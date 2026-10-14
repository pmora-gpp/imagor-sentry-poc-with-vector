"""Stand-in for Sentry's envelope endpoint: logs every event it receives instead of storing it.

Answers with MOCK_STATUS (default 200) so the forwarder's failure path can be exercised too.
"""
import json
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PORT = int(os.environ.get("PORT", "9000"))
STATUS = int(os.environ.get("MOCK_STATUS", "200"))


def log(msg):
    print(f"[mock-sentry] {msg}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        log(f"POST {self.path} -> answering {STATUS}")
        log(f"  X-Sentry-Auth: {self.headers.get('X-Sentry-Auth', '')}")
        log(f"  Content-Type:  {self.headers.get('Content-Type', '')}")
        event_id = uuid.uuid4().hex
        try:
            # envelope: header line, then (item header, item payload) line pairs
            lines = [json.loads(line) for line in body.decode("utf-8").splitlines() if line.strip()]
            envelope_header, items = lines[0], lines[1:]
            event_id = envelope_header.get("event_id", event_id)
            log(f"  envelope header: {json.dumps(envelope_header)}")
            for item_header, payload in zip(items[::2], items[1::2]):
                log(f"  item {json.dumps(item_header)}:")
                print(json.dumps(payload, indent=2), flush=True)
        except (ValueError, IndexError) as exc:
            log(f"  could not parse envelope ({exc!r}): {body[:500]!r}")

        response = json.dumps({"id": event_id}).encode("utf-8")
        self.send_response(STATUS)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response)))
        self.end_headers()
        self.wfile.write(response)

    def log_message(self, *args):
        pass  # replaced by the logging in do_POST


if __name__ == "__main__":
    log(f"listening on http://0.0.0.0:{PORT} (answering {STATUS})")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
