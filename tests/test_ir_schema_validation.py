"""IR JSON Schema Validation Tests.

Validates that every IR fixture in .termin.pkg packages conforms to the
Termin IR JSON Schema (specs/termin-ir-schema.json).

These tests catch drift between the compiler's actual output and the
published schema contract. If a field is in the IR but not the schema
(or vice versa), these tests will fail — keeping the schema and
compiler output in sync.

Authors: Jamie-Leigh Blake & Claude Anthropic
"""

import json
import zipfile
import pytest
from pathlib import Path

from jsonschema import validate, ValidationError, Draft202012Validator

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SPECS_DIR = Path(__file__).parent.parent / "specs"
SCHEMA_PATH = SPECS_DIR / "termin-ir-schema.json"


# ── Load schema once ──

@pytest.fixture(scope="session")
def ir_schema():
    """Load the IR JSON Schema."""
    with open(SCHEMA_PATH) as f:
        schema = json.load(f)
    # Validate the schema itself is well-formed
    Draft202012Validator.check_schema(schema)
    return schema


@pytest.fixture(scope="session")
def ir_validator(ir_schema):
    """Create a reusable validator instance."""
    return Draft202012Validator(ir_schema)


# ── Discover all IR from .termin.pkg packages ──

def _extract_ir_from_pkg(pkg_path: Path) -> dict:
    """Extract IR JSON from a .termin.pkg ZIP package."""
    with zipfile.ZipFile(pkg_path, 'r') as zf:
        manifest = json.loads(zf.read("manifest.json"))
        ir_json = zf.read(manifest["ir"]["entry"]).decode("utf-8")
        return json.loads(ir_json)


def _ir_fixture_files():
    """Return all .termin.pkg fixture files for parametrization."""
    files = sorted(FIXTURES_DIR.glob("*.termin.pkg"))
    if not files:
        pytest.skip("No .termin.pkg fixture files found")
    return files


def _ir_fixture_ids():
    """Return human-readable IDs for parametrization."""
    return [f.stem.replace(".termin", "") for f in _ir_fixture_files()]


# ═══════════════════════════════════════════════════════════════════════
# 1. FULL SCHEMA VALIDATION
# ═══════════════════════════════════════════════════════════════════════


class TestIRSchemaValidation:
    """Validate every IR fixture against the full JSON Schema.

    The schema uses additionalProperties: false throughout, so any
    extra fields in the IR will cause validation failures.
    """

    @pytest.mark.parametrize(
        "ir_file",
        _ir_fixture_files(),
        ids=_ir_fixture_ids(),
    )
    def test_ir_validates_against_schema(self, ir_file, ir_validator):
        """Each IR fixture must validate against the IR JSON Schema."""
        ir_data = _extract_ir_from_pkg(ir_file)

        errors = list(ir_validator.iter_errors(ir_data))
        if errors:
            # Build a detailed failure message
            messages = []
            for err in errors[:10]:  # cap at 10 to keep output readable
                path = " -> ".join(str(p) for p in err.absolute_path) or "(root)"
                messages.append(f"  [{path}] {err.message}")
            detail = "\n".join(messages)
            total = len(errors)
            pytest.fail(
                f"{ir_file.stem}: {total} schema validation error(s):\n{detail}"
            )


# ═══════════════════════════════════════════════════════════════════════
# 2. COMPUTE SPEC FIELD COMPLETENESS
# ═══════════════════════════════════════════════════════════════════════


class TestComputeSpecFields:
    """Validate that every ComputeSpec has the required v0.5.0 fields.

    These fields were added for the agent/LLM compute model and must
    be present in all compiled IR, even if defaulted to null/empty.
    """

    # Fields that should be present on every ComputeSpec
    REQUIRED_COMPUTE_FIELDS = {
        "name",       # QualifiedName — always required
        "shape",      # ComputeShape — always required
        "accesses",   # v0.5.0: boundary declaration for agent tool scoping
    }

    # Fields that should exist (with defaults) for completeness
    EXPECTED_COMPUTE_FIELDS = {
        "input_content", "output_content", "body_lines",
        "required_scope", "required_role",
        "input_params", "output_params",
        "client_safe", "identity_mode",
        "required_confidentiality_scopes", "output_confidentiality_scope",
        "field_dependencies",
        "provider", "preconditions", "postconditions",
        "directive", "objective", "strategy",
        "trigger", "trigger_where",
        "accesses", "input_fields", "output_fields", "output_creates",
    }

    @pytest.mark.parametrize(
        "ir_file",
        _ir_fixture_files(),
        ids=_ir_fixture_ids(),
    )
    def test_compute_specs_have_required_fields(self, ir_file):
        """Every ComputeSpec must have required fields present."""
        ir_data = _extract_ir_from_pkg(ir_file)

        computes = ir_data.get("computes", [])
        if not computes:
            pytest.skip(f"{ir_file.stem} has no computes")

        missing_report = []
        for i, compute in enumerate(computes):
            compute_name = compute.get("name", {}).get("display", f"compute[{i}]")
            missing = self.REQUIRED_COMPUTE_FIELDS - set(compute.keys())
            if missing:
                missing_report.append(
                    f"  Compute '{compute_name}': missing {sorted(missing)}"
                )

        if missing_report:
            detail = "\n".join(missing_report)
            pytest.fail(
                f"{ir_file.stem}: ComputeSpecs missing required fields:\n{detail}"
            )

    @pytest.mark.parametrize(
        "ir_file",
        _ir_fixture_files(),
        ids=_ir_fixture_ids(),
    )
    def test_compute_specs_have_expected_fields(self, ir_file):
        """Every ComputeSpec should have all expected fields for completeness."""
        ir_data = _extract_ir_from_pkg(ir_file)

        computes = ir_data.get("computes", [])
        if not computes:
            pytest.skip(f"{ir_file.stem} has no computes")

        missing_report = []
        for i, compute in enumerate(computes):
            compute_name = compute.get("name", {}).get("display", f"compute[{i}]")
            missing = self.EXPECTED_COMPUTE_FIELDS - set(compute.keys())
            if missing:
                missing_report.append(
                    f"  Compute '{compute_name}': missing {sorted(missing)}"
                )

        if missing_report:
            detail = "\n".join(missing_report)
            pytest.fail(
                f"{ir_file.stem}: ComputeSpecs missing expected fields:\n{detail}"
            )


# ═══════════════════════════════════════════════════════════════════════
# 3. CONTENT SCHEMA SINGULAR FIELD
# ═══════════════════════════════════════════════════════════════════════


class TestContentSchemaSingular:
    """Validate that every ContentSchema has a 'singular' field.

    The singular form (e.g., 'echo' for 'echoes') is used by the
    runtime for event context naming and must be present.
    """

    @pytest.mark.parametrize(
        "ir_file",
        _ir_fixture_files(),
        ids=_ir_fixture_ids(),
    )
    def test_content_schemas_have_singular(self, ir_file):
        """Every ContentSchema must have a 'singular' field."""
        ir_data = _extract_ir_from_pkg(ir_file)

        content_list = ir_data.get("content", [])
        if not content_list:
            pytest.skip(f"{ir_file.stem} has no content definitions")

        missing = []
        for i, content in enumerate(content_list):
            content_name = content.get("name", {}).get("display", f"content[{i}]")
            if "singular" not in content:
                missing.append(f"  Content '{content_name}': missing 'singular' field")

        if missing:
            detail = "\n".join(missing)
            pytest.fail(
                f"{ir_file.stem}: ContentSchemas missing 'singular':\n{detail}"
            )

    @pytest.mark.parametrize(
        "ir_file",
        _ir_fixture_files(),
        ids=_ir_fixture_ids(),
    )
    def test_singular_is_nonempty_string(self, ir_file):
        """The 'singular' field must be a non-empty string when present."""
        ir_data = _extract_ir_from_pkg(ir_file)

        content_list = ir_data.get("content", [])
        if not content_list:
            pytest.skip(f"{ir_file.stem} has no content definitions")

        bad = []
        for i, content in enumerate(content_list):
            content_name = content.get("name", {}).get("display", f"content[{i}]")
            singular = content.get("singular")
            if singular is not None and (not isinstance(singular, str) or singular == ""):
                bad.append(
                    f"  Content '{content_name}': singular is {singular!r} (expected non-empty string)"
                )

        if bad:
            detail = "\n".join(bad)
            pytest.fail(
                f"{ir_file.stem}: ContentSchemas with invalid 'singular':\n{detail}"
            )


# ═══════════════════════════════════════════════════════════════════════
# 4. STRUCTURAL INTEGRITY CHECKS
# ═══════════════════════════════════════════════════════════════════════


class TestIRStructuralIntegrity:
    """Cross-cutting structural checks beyond what JSON Schema catches."""

    @pytest.mark.parametrize(
        "ir_file",
        _ir_fixture_files(),
        ids=_ir_fixture_ids(),
    )
    def test_ir_version_is_present(self, ir_file):
        """Every IR must declare ir_version."""
        ir_data = _extract_ir_from_pkg(ir_file)
        assert "ir_version" in ir_data, f"{ir_file.stem}: missing ir_version"
        assert ir_data["ir_version"] == "0.9.0", (
            f"{ir_file.stem}: expected ir_version '0.9.0', got '{ir_data['ir_version']}'"
        )

    @pytest.mark.parametrize(
        "ir_file",
        _ir_fixture_files(),
        ids=_ir_fixture_ids(),
    )
    def test_all_top_level_keys_are_known(self, ir_file):
        """No unexpected top-level keys (schema has additionalProperties: false)."""
        ir_data = _extract_ir_from_pkg(ir_file)

        known_keys = {
            "ir_version", "reflection_enabled", "app_id",
            "name", "description", "auth",
            "content", "access_grants", "state_machines",
            "events", "routes", "pages", "nav_items", "streams",
            "computes", "channels", "boundaries",
            "error_handlers", "reclassification_points",
            # v0.9 Phase 5a.1: presentation contracts the IR's pages
            # require. Aggregated from `node.contract` across pages
            # at lower time. Used by deploy-time validation to enforce
            # that every required contract has a bound provider.
            "required_contracts",
        }
        extra = set(ir_data.keys()) - known_keys
        assert not extra, (
            f"{ir_file.stem}: unexpected top-level keys: {sorted(extra)}"
        )

    @pytest.mark.parametrize(
        "ir_file",
        _ir_fixture_files(),
        ids=_ir_fixture_ids(),
    )
    def test_content_names_are_qualified(self, ir_file):
        """Every Content 'name' must be a QualifiedName object with display/snake/pascal."""
        ir_data = _extract_ir_from_pkg(ir_file)

        for i, content in enumerate(ir_data.get("content", [])):
            name = content.get("name")
            assert isinstance(name, dict), (
                f"{ir_file.stem}: content[{i}].name is not an object"
            )
            for key in ("display", "snake", "pascal"):
                assert key in name, (
                    f"{ir_file.stem}: content[{i}].name missing '{key}'"
                )

    @pytest.mark.parametrize(
        "ir_file",
        _ir_fixture_files(),
        ids=_ir_fixture_ids(),
    )
    def test_state_machine_content_refs_exist(self, ir_file):
        """Every state machine's content_ref must point to a defined Content."""
        ir_data = _extract_ir_from_pkg(ir_file)

        content_names = {
            c["name"]["snake"] for c in ir_data.get("content", [])
        }
        # Also allow refs to channels, computes, boundaries
        channel_names = {
            c["name"]["snake"] for c in ir_data.get("channels", [])
        }
        compute_names = {
            c["name"]["snake"] for c in ir_data.get("computes", [])
        }
        boundary_names = {
            c["name"]["snake"] for c in ir_data.get("boundaries", [])
        }
        all_names = content_names | channel_names | compute_names | boundary_names

        for sm in ir_data.get("state_machines", []):
            ref = sm["content_ref"]
            assert ref in all_names, (
                f"{ir_file.stem}: state_machine '{sm['machine_name']}' "
                f"references unknown content_ref '{ref}'. "
                f"Known: {sorted(all_names)}"
            )

    @pytest.mark.parametrize(
        "ir_file",
        _ir_fixture_files(),
        ids=_ir_fixture_ids(),
    )
    def test_access_grants_have_nonempty_verbs(self, ir_file):
        """Every access_grant must have at least one verb (issue #007).

        Empty verbs arrays mean the compiler failed to parse a compound
        verb phrase like 'can view or create'. This is a security bug:
        it silently denies all operations for that scope+content combo.
        """
        ir_data = _extract_ir_from_pkg(ir_file)
        valid_verbs = {"VIEW", "CREATE", "UPDATE", "DELETE", "AUDIT"}

        empty_grants = []
        bad_verb_grants = []
        for i, grant in enumerate(ir_data.get("access_grants", [])):
            verbs = grant.get("verbs", [])
            if not verbs:
                empty_grants.append(
                    f"  grant[{i}]: {grant['content']}/{grant['scope']} has empty verbs"
                )
            for v in verbs:
                if v not in valid_verbs:
                    bad_verb_grants.append(
                        f"  grant[{i}]: {grant['content']}/{grant['scope']} "
                        f"has unrecognized verb '{v}'"
                    )

        errors = empty_grants + bad_verb_grants
        if errors:
            detail = "\n".join(errors)
            pytest.fail(f"{ir_file.stem}: access_grant verb issues:\n{detail}")

    @pytest.mark.parametrize(
        "ir_file",
        _ir_fixture_files(),
        ids=_ir_fixture_ids(),
    )
    def test_access_grants_reference_declared_scopes(self, ir_file):
        """Every access_grant scope must be declared in auth.scopes."""
        ir_data = _extract_ir_from_pkg(ir_file)

        declared_scopes = set(ir_data.get("auth", {}).get("scopes", []))
        if not declared_scopes:
            pytest.skip(f"{ir_file.stem} has no declared scopes")

        bad = []
        for i, grant in enumerate(ir_data.get("access_grants", [])):
            scope = grant.get("scope", "")
            if scope not in declared_scopes:
                bad.append(
                    f"  grant[{i}]: scope '{scope}' not in auth.scopes"
                )

        if bad:
            detail = "\n".join(bad)
            pytest.fail(
                f"{ir_file.stem}: access_grants reference undeclared scopes:\n{detail}"
            )
