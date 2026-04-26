"""Conformance — v0.9: cascade grammar (BRD §6.2).

Every conforming runtime must:

  1. **Schema**: For every reference field, the IR carries a non-null
     `cascade_mode` of either "cascade" or "restrict". The schema
     validates this invariant structurally (FieldSpec allOf if/then).

  2. **Cascade-on-delete behavior**: Deleting a parent record removes
     all child records that reference it via a `cascade on delete`
     field. The cascade propagates transitively: A → B → C cascade
     chains take all three when A is deleted.

  3. **Restrict-on-delete behavior**: Deleting a parent record while
     any child references it via a `restrict on delete` field returns
     HTTP 409 Conflict. Nothing is deleted.

  4. **Mixed children with restrict-takes-precedence**: A parent with
     both cascade-children AND restrict-children, when the
     restrict-children exist, refuses delete with 409 — and NOTHING
     is deleted (transactional). After clearing the restrict-children,
     parent delete succeeds and cascade-children are removed.

  5. **NULL-FK referrers** are unaffected by cascade-deletes of other
     parents. A child with a NULL optional cascade reference is not
     touched by any parent delete.

  6. **Self-cascade**: A content's self-reference may declare
     `cascade on delete`. Deleting a node removes the entire subtree
     reachable through that field.

The fixtures used here are purpose-built for cascade testing. They
are NOT examples of real applications; they exercise specific cascade
shapes that real apps may compose.

Test ID convention: `v09_cas_NN_` matches the design doc tracking IDs.
Run with `pytest tests/test_v09_cascade.py -k v09_cas_03` to filter.
"""

import json
import zipfile
from pathlib import Path

import jsonschema
import pytest


CONFORMANCE_ROOT = Path(__file__).parent.parent
CASCADE_FIXTURES_DIR = CONFORMANCE_ROOT / "fixtures-cascade"
SCHEMA_PATH = CONFORMANCE_ROOT / "specs" / "termin-ir-schema.json"


# ── Helpers ──


def _create_parent(session, label: str = "P-A"):
    session.set_role("tester")
    r = session.post("/api/v1/parents", json={"name": label})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_cascade_child(session, parent_id, label: str = "C-A"):
    r = session.post("/api/v1/cascade_children", json={
        "label": label, "parent": parent_id})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _create_restrict_child(session, parent_id, label: str = "R-A"):
    r = session.post("/api/v1/restrict_children", json={
        "label": label, "parent": parent_id})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _delete_parent(session, parent_id):
    return session.delete(f"/api/v1/parents/{parent_id}")


def _read_ir_from_pkg(pkg_path: Path) -> dict:
    with zipfile.ZipFile(pkg_path) as z:
        ir_files = [n for n in z.namelist() if n.endswith(".ir.json")]
        assert ir_files, f"no IR file in {pkg_path}"
        return json.loads(z.read(ir_files[0]))


# ─────────────────────────────────────────────────────────────────────
# Schema (v09_cas_01..03)
# ─────────────────────────────────────────────────────────────────────

class TestCascadeIRSchema:
    """The IR contract for cascade_mode."""

    def test_v09_cas_01_reference_fields_have_cascade_mode(self):
        """Every reference field in every cascade fixture has a non-
        null cascade_mode in {cascade, restrict}.
        """
        for pkg in CASCADE_FIXTURES_DIR.glob("*.termin.pkg"):
            ir = _read_ir_from_pkg(pkg)
            for content in ir["content"]:
                for field in content["fields"]:
                    if field.get("foreign_key") is None:
                        continue
                    cm = field.get("cascade_mode")
                    assert cm in ("cascade", "restrict"), (
                        f"{pkg.name} {content['name']['snake']}.{field['name']} "
                        f"has cascade_mode={cm!r} (expected 'cascade' or 'restrict')"
                    )

    def test_v09_cas_02_non_reference_fields_have_null_cascade_mode(self):
        """Non-reference fields must have cascade_mode null."""
        for pkg in CASCADE_FIXTURES_DIR.glob("*.termin.pkg"):
            ir = _read_ir_from_pkg(pkg)
            for content in ir["content"]:
                for field in content["fields"]:
                    if field.get("foreign_key") is not None:
                        continue
                    cm = field.get("cascade_mode")
                    assert cm is None, (
                        f"{pkg.name} {content['name']['snake']}.{field['name']} "
                        f"is a non-reference but has cascade_mode={cm!r}"
                    )

    def test_v09_cas_03_ir_validates_against_schema(self):
        """Every cascade fixture's IR validates against the JSON
        schema, including the new FieldSpec if/then/else invariant.
        """
        if not SCHEMA_PATH.exists():
            pytest.skip(f"schema not present at {SCHEMA_PATH}")
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        for pkg in CASCADE_FIXTURES_DIR.glob("*.termin.pkg"):
            ir = _read_ir_from_pkg(pkg)
            try:
                jsonschema.validate(ir, schema)
            except jsonschema.ValidationError as e:
                pytest.fail(
                    f"{pkg.name} fails IR schema validation: {e.message}\n"
                    f"path: {list(e.absolute_path)}"
                )


# ─────────────────────────────────────────────────────────────────────
# Cascade behavior (v09_cas_10..15)
# ─────────────────────────────────────────────────────────────────────

class TestCascadeBehavior:
    """Runtime cascade-on-delete must propagate to children."""

    def test_v09_cas_10_delete_parent_with_no_children_succeeds(
            self, cascade_demo):
        """A parent with no children deletes cleanly."""
        pid = _create_parent(cascade_demo, label="P-empty")
        r = _delete_parent(cascade_demo, pid)
        assert r.status_code == 200, r.text
        # Confirm gone.
        assert cascade_demo.get(f"/api/v1/parents/{pid}").status_code == 404

    def test_v09_cas_11_delete_parent_cascades_to_cascade_children(
            self, cascade_demo):
        """Parent delete removes cascade children."""
        pid = _create_parent(cascade_demo, label="P-cas")
        cid = _create_cascade_child(cascade_demo, pid, label="C-cas")

        r = _delete_parent(cascade_demo, pid)
        assert r.status_code == 200, r.text

        # Cascade child must be gone.
        assert cascade_demo.get(f"/api/v1/cascade_children/{cid}").status_code == 404

    def test_v09_cas_12_delete_parent_restricted_returns_409(
            self, cascade_demo):
        """Parent delete refused while restrict children exist."""
        pid = _create_parent(cascade_demo, label="P-res")
        rcid = _create_restrict_child(cascade_demo, pid, label="R-res")

        r = _delete_parent(cascade_demo, pid)
        assert r.status_code == 409, r.text

        # Both records still exist.
        assert cascade_demo.get(f"/api/v1/parents/{pid}").status_code == 200
        assert cascade_demo.get(f"/api/v1/restrict_children/{rcid}").status_code == 200


# ─────────────────────────────────────────────────────────────────────
# Self-cascade (v09_cas_20)
# ─────────────────────────────────────────────────────────────────────

class TestSelfCascade:
    def test_v09_cas_20_self_cascade_subtree(self, cascade_self_ref):
        """A self-cascade-on-delete reference deletes the subtree
        reachable through that field.

        Build a tree:

            root
            ├── childA
            │    └── grandA
            └── childB
        """
        s = cascade_self_ref
        s.set_role("tester")
        r = s.post("/api/v1/tree_nodes", json={"label": "root"})
        assert r.status_code == 201, r.text
        root = r.json()["id"]

        r = s.post("/api/v1/tree_nodes", json={
            "label": "childA", "parent": root})
        child_a = r.json()["id"]
        r = s.post("/api/v1/tree_nodes", json={
            "label": "childB", "parent": root})
        child_b = r.json()["id"]
        r = s.post("/api/v1/tree_nodes", json={
            "label": "grandA", "parent": child_a})
        grand_a = r.json()["id"]

        # Delete the root → entire subtree gone.
        r = s.delete(f"/api/v1/tree_nodes/{root}")
        assert r.status_code == 200, r.text

        for node_id, name in [(root, "root"), (child_a, "childA"),
                              (child_b, "childB"), (grand_a, "grandA")]:
            r = s.get(f"/api/v1/tree_nodes/{node_id}")
            assert r.status_code == 404, (
                f"{name} (id {node_id}) should have been cascade-deleted: "
                f"got {r.status_code} {r.text}")


# ─────────────────────────────────────────────────────────────────────
# Optional FK + cascade (v09_cas_30)
# ─────────────────────────────────────────────────────────────────────

class TestOptionalCascade:
    def test_v09_cas_30_null_fk_unaffected_by_other_cascade(
            self, cascade_optional):
        """A child with NULL optional cascade-FK is untouched when an
        unrelated parent is deleted.
        """
        s = cascade_optional
        s.set_role("tester")

        r = s.post("/api/v1/categories", json={"name": "real-cat"})
        assert r.status_code == 201, r.text
        real_cat_id = r.json()["id"]

        r = s.post("/api/v1/items", json={
            "label": "linked", "category": real_cat_id})
        assert r.status_code == 201, r.text
        linked = r.json()["id"]

        r = s.post("/api/v1/items", json={"label": "orphan"})
        assert r.status_code == 201, r.text
        orphan = r.json()["id"]

        # Delete real category → linked item cascade-deleted, orphan untouched.
        r = s.delete(f"/api/v1/categories/{real_cat_id}")
        assert r.status_code == 200, r.text

        assert s.get(f"/api/v1/items/{linked}").status_code == 404
        assert s.get(f"/api/v1/items/{orphan}").status_code == 200


# ─────────────────────────────────────────────────────────────────────
# Multi-hop cascade (v09_cas_40)
# ─────────────────────────────────────────────────────────────────────

class TestMultiHopCascade:
    def test_v09_cas_40_three_hop_cascade_chain(self, cascade_multihop_ok):
        """A → B → C all cascade. Delete A → B and C are gone."""
        s = cascade_multihop_ok
        s.set_role("tester")

        r = s.post("/api/v1/as", json={"label": "a-1"})
        assert r.status_code == 201, r.text
        a_id = r.json()["id"]

        r = s.post("/api/v1/bs", json={"label": "b-1", "a": a_id})
        assert r.status_code == 201, r.text
        b_id = r.json()["id"]

        r = s.post("/api/v1/cs", json={"label": "c-1", "b": b_id})
        assert r.status_code == 201, r.text
        c_id = r.json()["id"]

        r = s.delete(f"/api/v1/as/{a_id}")
        assert r.status_code == 200, r.text

        assert s.get(f"/api/v1/as/{a_id}").status_code == 404
        assert s.get(f"/api/v1/bs/{b_id}").status_code == 404
        assert s.get(f"/api/v1/cs/{c_id}").status_code == 404
