#!/usr/bin/env python3
"""Minimal Ascender API double for tests/run-scenario.sh.

Serves only the endpoints build_inventory.yml touches and deliberately never
returns the inventory source it accepts, which is what a real Ascender does
while a newly created object is not yet queryable. This lets scenario
T-ASCENDER-INVENTORY-BOOTSTRAP-005 (retry budget exhausted) run without a live
Ascender.

This is a test double, not a substitute for a live run: scenarios -001 to -004,
-006 and -007 are only meaningful against a real Ascender.
"""

import argparse
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ORG = {"id": 1, "name": "20031", "type": "organization", "url": "/api/v2/organizations/1/"}
PROJECT = {"id": 3, "name": "rel_labs", "type": "project", "url": "/api/v2/projects/3/"}
TOKEN = {"id": 1, "token": "stub-token", "scope": "write"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "StubAscender/1.0"

    # --- helpers ---------------------------------------------------------
    def log_message(self, fmt, *args):  # keep the harness log readable
        sys.stderr.write("stub: " + (fmt % args) + "\n")

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except ValueError:
            return {}

    def _send(self, status, payload=None, headers=None):
        body = b"" if payload is None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _list(self, results):
        return {"count": len(results), "next": None, "previous": None, "results": results}

    def _url(self, path, item_id):
        return "http://%s/api/v2/%s/%s/" % (self.headers.get("Host"), path, item_id)

    # --- routes ----------------------------------------------------------
    def do_POST(self):
        path = self.path.split("?")[0]
        body = self._body()

        if path == "/api/v2/tokens/":
            return self._send(201, TOKEN)

        if path == "/api/v2/inventories/":
            inventory = {
                "id": 2,
                "name": body.get("name", "20031 Inventory"),
                "description": body.get("description", ""),
                "organization": body.get("organization", ORG["id"]),
                "kind": "",
                "url": self._url("inventories", 2),
            }
            self.server.inventories.append(inventory)
            return self._send(201, inventory)

        if path == "/api/v2/inventory_sources/":
            source = {
                "id": 4,
                "name": body.get("name", "20031-source"),
                "inventory": body.get("inventory", 2),
                "source": body.get("source", "scm"),
                "url": self._url("inventory_sources", 4),
                "related": {"update": "/api/v2/inventory_sources/4/update/"},
            }
            # Deliberately not added to the list view: the wait must time out.
            self.server.inventory_sources.append(source)
            return self._send(201, source)

        return self._send(404, {"detail": "Not found."})

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/api/v2/organizations/":
            return self._send(200, self._list([ORG]))
        if path == "/api/v2/inventories/":
            return self._send(200, self._list(self.server.inventories))
        if path == "/api/v2/projects/":
            return self._send(200, self._list([PROJECT]))
        if path == "/api/v2/inventory_sources/":
            # Always empty: models an object that never becomes queryable.
            return self._send(200, self._list([]))
        if re.match(r"^/api/v2/inventory_sources/\d+/$", path):
            return self._send(404, {"detail": "Not found."})

        return self._send(404, {"detail": "Not found."})

    def do_DELETE(self):
        # Token release on logout; nothing to do.
        return self._send(204)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address):
        super().__init__(address, Handler)
        self.inventories = []
        self.inventory_sources = []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True, help="TCP port to listen on (127.0.0.1)")
    args = parser.parse_args()
    server = Server(("127.0.0.1", args.port))
    sys.stderr.write("stub: listening on http://127.0.0.1:%d\n" % args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
