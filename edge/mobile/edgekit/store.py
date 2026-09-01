"""FamilyStore — namespaces, EdgeResources, and the offline-first queue.

SQLite (stdlib) with JSON TEXT properties: the JSONB half of the
violet_rails transplant. Every resource is scoped to a family_id. Sync is
simulated honestly: resources created while the store is 'offline' queue
locally and move to 'synced' only after connectivity returns and sync()
runs — the acceptance scripts flip this flag instead of pretending.
"""

import json
import sqlite3
import time

from .actions import ActionRegistry

_SCHEMA = """
CREATE TABLE IF NOT EXISTS namespace (
  id INTEGER PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  version INTEGER NOT NULL,
  properties_template TEXT NOT NULL,
  client_actions TEXT NOT NULL,
  sync_mode TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS edge_resource (
  id INTEGER PRIMARY KEY,
  namespace_id INTEGER NOT NULL REFERENCES namespace(id),
  family_id INTEGER NOT NULL,
  properties TEXT NOT NULL,
  source_ref TEXT,
  sync_state TEXT NOT NULL DEFAULT 'local',
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS edge_resource_ns_family_idx
  ON edge_resource(namespace_id, family_id);
"""


class BundleError(ValueError):
    pass


class FamilyStore:
    def __init__(self, path=":memory:", registry=None):
        # check_same_thread=False so a threaded HTTP server can hold one
        # store; the store itself is NOT thread-safe — callers serialize
        # access with their own lock (see the demo serve.py files).
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self.registry = registry or ActionRegistry()
        self.online = True
        self.ctx_extra = {}

    # -- bundles ---------------------------------------------------------

    def install_bundle(self, bundle):
        """Install a namespace bundle (the violet export/import analog).

        Required keys: slug, version, properties (template dict),
        client_actions (list of {name, params}), sync_mode
        (none|opt_in|always).
        """
        for key in ("slug", "version", "properties", "client_actions",
                    "sync_mode"):
            if key not in bundle:
                raise BundleError(f"bundle missing {key!r}")
        if bundle["sync_mode"] not in ("none", "opt_in", "always"):
            raise BundleError(f"bad sync_mode {bundle['sync_mode']!r}")
        for spec in bundle["client_actions"]:
            if spec["name"] not in self.registry.names():
                raise BundleError(
                    f"bundle wants unregistered action {spec['name']!r}")
        self.db.execute(
            "INSERT OR REPLACE INTO namespace "
            "(slug, version, properties_template, client_actions, sync_mode) "
            "VALUES (?,?,?,?,?)",
            (bundle["slug"], bundle["version"],
             json.dumps(bundle["properties"]),
             json.dumps(bundle["client_actions"]),
             bundle["sync_mode"]))
        self.db.commit()
        return self.namespace(bundle["slug"])

    def namespace(self, slug):
        row = self.db.execute(
            "SELECT * FROM namespace WHERE slug=?", (slug,)).fetchone()
        if row is None:
            raise BundleError(f"namespace {slug!r} not installed")
        return {
            "id": row["id"],
            "slug": row["slug"],
            "version": row["version"],
            "properties_template": json.loads(row["properties_template"]),
            "client_actions": json.loads(row["client_actions"]),
            "sync_mode": row["sync_mode"],
        }

    # -- resources -------------------------------------------------------

    def create(self, slug, properties, family_id=1, source_ref=None,
               provider=None):
        """Validate against the template, run client actions, persist."""
        ns = self.namespace(slug)
        template = ns["properties_template"]
        props = dict(properties)
        for field, spec in template.items():
            if spec.get("required") and props.get(field) in (None, ""):
                raise BundleError(f"{slug}: required field {field!r} missing")
            if field not in props and "default" in spec:
                props[field] = spec["default"]
        unknown = set(props) - set(template)
        if unknown:
            raise BundleError(f"{slug}: unknown fields {sorted(unknown)}")

        # Explicit provider wins over ctx_extra; the store reference is
        # always ours. (A negative-control provider passed to create() must
        # never be silently shadowed by the store-level default.)
        ctx = {**self.ctx_extra, "store": self, "family_id": family_id}
        if provider is not None:
            ctx["provider"] = provider
        ctx.setdefault("provider", None)
        for spec in ns["client_actions"]:
            self.registry.run(spec["name"], props, spec.get("params"), ctx)

        # Re-validate after actions: an action must not persist fields the
        # namespace template does not declare.
        unknown = set(props) - set(template)
        if unknown:
            raise BundleError(
                f"{slug}: action wrote off-template fields {sorted(unknown)}")

        sync_state = ("local" if ns["sync_mode"] == "none"
                      else ("queued" if not self.online else "synced"))
        cur = self.db.execute(
            "INSERT INTO edge_resource "
            "(namespace_id, family_id, properties, source_ref, sync_state, "
            " created_at) VALUES (?,?,?,?,?,?)",
            (ns["id"], family_id, json.dumps(props), source_ref, sync_state,
             time.time()))
        self.db.commit()
        return self.get(cur.lastrowid)

    def get(self, resource_id):
        row = self.db.execute(
            "SELECT * FROM edge_resource WHERE id=?",
            (resource_id,)).fetchone()
        if row is None:
            raise KeyError(resource_id)
        return self._to_dict(row)

    def query(self, slug, family_id=1, where=None):
        """where: optional {property: value} equality filters (JSON)."""
        ns = self.namespace(slug)
        rows = self.db.execute(
            "SELECT * FROM edge_resource "
            "WHERE namespace_id=? AND family_id=? ORDER BY id",
            (ns["id"], family_id)).fetchall()
        out = [self._to_dict(r) for r in rows]
        if where:
            out = [r for r in out
                   if all(r["properties"].get(k) == v
                          for k, v in where.items())]
        return out

    def update(self, resource_id, properties):
        res = self.get(resource_id)
        res["properties"].update(properties)
        self.db.execute(
            "UPDATE edge_resource SET properties=? WHERE id=?",
            (json.dumps(res["properties"]), resource_id))
        self.db.commit()
        return self.get(resource_id)

    # -- offline-first sync ----------------------------------------------

    def set_online(self, online):
        self.online = bool(online)

    def sync(self):
        """Deliver queued resources; a no-op offline. Returns count."""
        if not self.online:
            return 0
        cur = self.db.execute(
            "UPDATE edge_resource SET sync_state='synced' "
            "WHERE sync_state='queued'")
        self.db.commit()
        return cur.rowcount

    def _to_dict(self, row):
        return {
            "id": row["id"],
            "family_id": row["family_id"],
            "properties": json.loads(row["properties"]),
            "source_ref": row["source_ref"],
            "sync_state": row["sync_state"],
            "created_at": row["created_at"],
        }
