#!/usr/bin/env python3
"""Minimal Ascender API double for the Molecule scenarios under molecule/.

Serves only the endpoints the control-plane playbooks touch: inventory and
job-template creates and filtered list views, field updates (PATCH), and the
inventory-source update call, which the real API answers with a job record.

This is a test double, not a substitute for a live run: the happy-path
scenarios are only meaningful against a real Ascender (the ``live``
scenario).

Fixed port (overridable with --port): the scenario molecule.yml files set
the CONTROLLER_* environment from this port, so it must be stable within a
run; an uncommon port keeps collisions with dev-machine services unlikely.

State knobs (environment variables, all off/empty by default; the scenario
molecule.yml files set them per scenario):

  MOLECULE_STUB_SEED=inventory
      Pre-populate the "20031 Inventory" inventory (no source) so the run
      converges a partially bootstrapped state.
  MOLECULE_STUB_SEED=stale-source
      Pre-populate the inventory and a "20031-source" whose source_path
      differs from the playbook's, so the run patches it and re-triggers
      the update.
  MOLECULE_STUB_SOURCE_NEVER_VISIBLE=1
      Created inventory sources are never added to the list view, so the
      source visibility wait exhausts its retry budget (the exhaust
      scenario).
  MOLECULE_STUB_INVENTORY_DELAY_SECONDS=<n>
      Created inventories are withheld from the list view for n seconds,
      so the inventory visibility wait genuinely polls.
  MOLECULE_STUB_SOURCE_DELAY_SECONDS=<n>
      Same for created inventory sources.
"""

import argparse
import json
import os
import re
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

DEFAULT_PORT = 18071

ORG = {"id": 1, "name": "20031", "type": "organization", "url": "/api/v2/organizations/1/"}
# The projects list view filters on organization (the modules resolve
# source_project with a name + organization query), so the record carries it.
PROJECT = {"id": 3, "name": "rel_labs", "organization": 1, "type": "project", "url": "/api/v2/projects/3/"}
TOKEN = {"id": 1, "token": "stub-token", "scope": "write"}

# Collections the playbooks create objects in, with the object type label the
# API reports on every record. The module update path reads
# existing_item['type'] and ['url'] before comparing fields, so both must be
# on every stored record (they are: the create and seed paths add them).
TYPES = {
    "inventories": "inventory",
    "inventory_sources": "inventory_source",
    "job_templates": "job_template",
    "jobs": "job",
}

# Fields the real API returns even when the create body omits them. The
# inventory module reads existing_item['kind'] on every run, so an inventory
# record must always carry it.
DEFAULT_FIELDS = {
    "inventories": {"kind": ""},
    "inventory_sources": {},
    "job_templates": {},
    "jobs": {},
}

# List-view params that are not record fields and must not be matched against.
IGNORED_FILTERS = {"page", "page_size", "order_by"}


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
        # Relative, like the real API: the module's update path hands the
        # record's url straight to build_url(), which only understands
        # paths (an absolute URL would be mangled into /api/v2/http://...).
        return "/api/v2/%s/%s/" % (path, item_id)

    def _find(self, collection, item_id):
        for record in self.server.collections[collection]:
            if record["id"] == item_id:
                return record
        return None

    def _visible(self, collection, record):
        # Created objects may be withheld from the views until a delay
        # elapses (or forever, in never-visible mode); seeded records are
        # visible from server start.
        hidden_until = self.server.hidden_until.get((collection, record["id"]))
        return hidden_until is None or time.monotonic() >= hidden_until

    def _filtered(self, collection, params):
        # AWX list-view filters: plain params are AND-ed; or__* params are
        # OR-ed against each other (the modules query with
        # or__id/or__name when given a numeric name_or_id).
        or_keys = [key[4:] for key in params if key.startswith("or__")]
        plain = {
            key: values[0]
            for key, values in params.items()
            if not key.startswith("or__") and key not in IGNORED_FILTERS
        }
        matched = []
        for record in self.server.collections[collection]:
            if not self._visible(collection, record):
                continue
            if any(str(record.get(key, "")) != value for key, value in plain.items()):
                continue
            if or_keys and not any(
                str(record.get(key, "")) == params["or__" + key][0] for key in or_keys
            ):
                continue
            matched.append(record)
        return matched

    def _record(self, collection):
        # The create path stores the request body verbatim (echoing every
        # module-managed field exactly as sent) plus the server-side fields.
        body = self._body()
        next_id = self.server.next_id[collection]
        self.server.next_id[collection] += 1
        record = dict(DEFAULT_FIELDS[collection])
        record.update(body)
        record["id"] = next_id
        record["type"] = TYPES[collection]
        record["url"] = self._url(collection, next_id)
        if collection == "inventory_sources":
            # The update module posts to the source's related update URL.
            record["related"] = {"update": self._url(collection, next_id) + "update/"}
        self.server.collections[collection].append(record)
        if collection == "inventories" and self.server.inventory_delay:
            self.server.hidden_until[(collection, record["id"])] = (
                time.monotonic() + self.server.inventory_delay
            )
        elif collection == "inventory_sources" and self.server.source_never_visible:
            self.server.hidden_until[(collection, record["id"])] = float("inf")
        elif collection == "inventory_sources" and self.server.source_delay:
            self.server.hidden_until[(collection, record["id"])] = (
                time.monotonic() + self.server.source_delay
            )
        return record

    # --- routes ----------------------------------------------------------
    def do_POST(self):
        path = self.path.split("?")[0]

        if path == "/api/v2/tokens/":
            return self._send(201, TOKEN)

        if path in ("/api/v2/inventories/", "/api/v2/inventory_sources/", "/api/v2/job_templates/"):
            collection = path.strip("/").split("/")[2]
            return self._send(201, self._record(collection))

        match = re.match(r"^/api/v2/inventory_sources/(\d+)/update/$", path)
        if match:
            source = self._find("inventory_sources", int(match.group(1)))
            if source is None:
                return self._send(404, {"detail": "Not found."})
            inventory = self._find("inventories", source.get("inventory"))
            job_id = self.server.next_id["jobs"]
            self.server.next_id["jobs"] += 1
            job = {
                "id": job_id,
                "name": "%s (%s) Update"
                % (source.get("name", ""), inventory.get("name", "") if inventory else ""),
                "job_type": "inventory_update",
                "inventory_source": source["id"],
                "inventory": source.get("inventory"),
                "status": "pending",
                "type": "job",
                "url": self._url("jobs", job_id),
            }
            self.server.collections["jobs"].append(job)
            return self._send(202, job)

        return self._send(404, {"detail": "Not found."})

    def do_GET(self):
        path = self.path.split("?")[0]
        query = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "")

        if path == "/api/v2/organizations/":
            return self._send(200, self._list(self._filtered_static([ORG], query)))
        if path == "/api/v2/projects/":
            return self._send(200, self._list(self._filtered_static([PROJECT], query)))

        if path in ("/api/v2/inventories/", "/api/v2/inventory_sources/",
                    "/api/v2/job_templates/", "/api/v2/jobs/"):
            collection = path.strip("/").split("/")[2]
            return self._send(200, self._list(self._filtered(collection, query)))

        match = re.match(r"^/api/v2/(inventories|inventory_sources|job_templates|jobs)/(\d+)/$", path)
        if match:
            record = self._find(match.group(1), int(match.group(2)))
            if record is None or not self._visible(match.group(1), record):
                # Not yet queryable: model the real API's not-found.
                return self._send(404, {"detail": "Not found."})
            return self._send(200, record)

        return self._send(404, {"detail": "Not found."})

    @staticmethod
    def _filtered_static(records, params):
        # Same AND/or__ filter as _filtered, for the static single-record
        # collections (organizations, projects).
        or_keys = [key[4:] for key in params if key.startswith("or__")]
        plain = {
            key: values[0]
            for key, values in params.items()
            if not key.startswith("or__") and key not in IGNORED_FILTERS
        }
        matched = []
        for record in records:
            if any(str(record.get(key, "")) != value for key, value in plain.items()):
                continue
            if or_keys and not any(
                str(record.get(key, "")) == params["or__" + key][0] for key in or_keys
            ):
                continue
            matched.append(record)
        return matched

    def do_PATCH(self):
        match = re.match(r"^/api/v2/(inventories|inventory_sources|job_templates)/(\d+)/$",
                         self.path.split("?")[0])
        if not match:
            return self._send(404, {"detail": "Not found."})
        record = self._find(match.group(1), int(match.group(2)))
        if record is None:
            return self._send(404, {"detail": "Not found."})
        # Apply the sent fields to the existing record, the way the real API
        # does; the module's update path re-reads the response and compares
        # the fields it sent, so an exact echo reports no further change.
        record.update(self._body())
        return self._send(200, record)

    def do_DELETE(self):
        # Token release on logout; nothing to do.
        return self._send(204)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address):
        super().__init__(address, Handler)
        self.collections = {
            "inventories": [],
            "inventory_sources": [],
            "job_templates": [],
            "jobs": [],
        }
        self.next_id = {
            "inventories": 2,  # 1 stays the organization id
            "inventory_sources": 4,  # 2/3 stay the inventory/project ids
            "job_templates": 5,
            "jobs": 10,
        }
        # State knobs (see the module docstring); parsed once at startup.
        self.inventory_delay = self._env_float("MOLECULE_STUB_INVENTORY_DELAY_SECONDS")
        self.source_delay = self._env_float("MOLECULE_STUB_SOURCE_DELAY_SECONDS")
        self.source_never_visible = os.environ.get("MOLECULE_STUB_SOURCE_NEVER_VISIBLE") == "1"
        self.hidden_until = {}
        self._seed(os.environ.get("MOLECULE_STUB_SEED") or "")

    @staticmethod
    def _env_float(name):
        raw = os.environ.get(name)
        if not raw:
            return 0.0
        try:
            return float(raw)
        except ValueError:
            raise SystemExit("stub: %s must be a number of seconds, got %r" % (name, raw))

    def _seed(self, seed):
        # Seeded records are created with the exact fields the playbooks set
        # (so their tasks report no change unless a knob says otherwise) and
        # are visible from server start.
        if seed == "inventory":
            self._seed_inventory()
        elif seed == "stale-source":
            self._seed_source(self._seed_inventory(), "inventory/stale.yml")
        elif seed:
            raise SystemExit("stub: unknown MOLECULE_STUB_SEED %r (want inventory|stale-source)" % seed)

    def _seed_inventory(self):
        inventory_id = self.next_id["inventories"]
        record = {
            "name": "20031 Inventory",
            "description": "My Default Inventory",
            "organization": ORG["id"],
            "kind": "",
            "id": inventory_id,
            "type": TYPES["inventories"],
            "url": "/api/v2/inventories/%d/" % inventory_id,
        }
        self.next_id["inventories"] += 1
        self.collections["inventories"].append(record)
        return inventory_id

    def _seed_source(self, inventory_id, source_path):
        source_id = self.next_id["inventory_sources"]
        record = {
            "name": "20031-source",
            "description": "20031 Inventory",
            "source_path": source_path,
            "source": "scm",
            "source_project": PROJECT["id"],
            "inventory": inventory_id,
            "overwrite": True,
            "update_on_launch": True,
            "id": source_id,
            "type": TYPES["inventory_sources"],
            "url": "/api/v2/inventory_sources/%d/" % source_id,
            "related": {"update": "/api/v2/inventory_sources/%d/update/" % source_id},
        }
        self.next_id["inventory_sources"] += 1
        self.collections["inventory_sources"].append(record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="TCP port to listen on (127.0.0.1); default %d" % DEFAULT_PORT,
    )
    args = parser.parse_args()
    server = Server(("127.0.0.1", args.port))
    sys.stderr.write("stub: listening on http://127.0.0.1:%d\n" % args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
