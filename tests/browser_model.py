"""Synthetic Chat Completions fixture. Never evidence of model quality."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread


class Fixture(BaseHTTPRequestHandler):
    teaching_calls = 0

    def log_message(self, *_args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        try:
            envelope = json.loads(body["messages"][-1]["content"])
        except (ValueError, KeyError):
            envelope = {}
        request = envelope.get("request", {})
        if request.get("task") == "role_teaching":
            type(self).teaching_calls += 1
            if type(self).teaching_calls == 1:
                self.send_error(503, "Synthetic teaching failure")
                return
        value = {}
        for key, spec in envelope.get("schema", {}).get("properties", {}).items():
            if "enum" in spec:
                # Deliberate simple legal policy, not a strategic NPC replacement.
                value[key] = next((v for v in spec["enum"] if v is not None), None) if key == "target" else None
            elif spec.get("type") == "boolean":
                value[key] = key == "ready"
            elif spec.get("type") == "string":
                value[key] = "Synthetic test response; no real model was invoked."
            else:
                value[key] = None
        content = json.dumps(value) if value else "Synthetic host review."
        encoded = json.dumps({"choices": [{"message": {"role": "assistant", "content": content}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def start_fixture():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
    Thread(target=server.serve_forever, daemon=True).start()
    return server
