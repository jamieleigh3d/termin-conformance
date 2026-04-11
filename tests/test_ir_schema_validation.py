"""IR JSON Schema Validation Tests.

Validates that every IR fixture in fixtures/ir/ conforms to the
Termin IR JSON Schema (fixtures/termin-ir-schema.json).

These tests catch drift between the compiler's actual output and the
published schema contract. If a field is in the IR but not the schema
(or vice versa), these tests will fail — keeping the schema and
compiler output in sync.

Authors: Jamie-Leigh Blake & Claude Anthropic
"""

import json
import pytest
from pathlib import Path

from jsonschema import validate, ValidationError, Draft202012Validator

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
SCHEMA_PATH = FIXTURES_DIR / "termin-ir-schema.json"
IR_DIR = FIXTURES_DIR / "ir"


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


# ── Discover all IR fixture files ──

def _ir_fixture_files():
    """Return all IR JSON fixture files for parametrization."""
    files = sorted(IR_DIR.glob("*_ir.json"))
    if not files:
        pytest.skip("No IR fixture files found in fixtures/ir/")
    return files


def _ir_fixture_ids():
    """Return human-readable IDs for parametrization."""
    return [f.stem.replace("_ir", "") for f in _ir_fixture_files()]


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
        with open(ir_file) as f:
            ir_data = json.load(f)

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
                f"{ir_file.name}: {total} schema validation error(s):\n{detail}"
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
        with open(ir_file) as f:
            ir_data = json.load(f)

        computes = ir_data.get("computes", [])
        if not computes:
            pytest.skip(f"{ir_file.name} has no computes")

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
                f"{ir_file.name}: ComputeSpecs missing required fields:\n{detail}"
            )

    @pytest.mark.parametrize(
        "ir_file",
        _ir_fixture_files(),
        ids=_ir_fixture_ids(),
    )
    def test_compute_specs_have_expected_fields(self, ir_file):
        """Every ComputeSpec should have all expected fields for completeness."""
        with open(ir_file) as f:
            ir_data = json.load(f)

        computes = ir_data.get("computes", [])
        if not computes:
            pytest.skip(f"{ir_file.name} has no computes")

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
                f"{ir_file.name}: ComputeSpecs missing expected fields:\n{detail}"
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
        with open(ir_file) as f:
            ir_data = json.load(f)

        content_list = ir_data.get("content", [])
        if not content_list:
            pytest.skip(f"{ir_file.name} has no content definitions")

        missing = []
        for i, content in enumerate(content_list):
            content_name = content.get("name", {}).get("display", f"content[{i}]")
            if "singular" not in content:
                missing.append(f"  Content '{content_name}': missing 'singular' field")

        if missing:
            detail = "\n".join(missing)
            pytest.fail(
                f"{ir_file.name}: ContentSchemas missing 'singular':\n{detail}"
            )

    @pytest.mark.parametrize(
        "ir_file",
        _ir_fixture_files(),
        ids=_ir_fixture_ids(),
    )
    def test_singular_is_nonempty_string(self, ir_file):
        """The 'singular' field must be a non-empty string when present."""
        with open(ir_file) as f:
            ir_data = json.load(f)

        content_list = ir_data.get("content", [])
        if not content_list:
            pytest.skip(f"{ir_file.name} has no content definitions")

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
                f"{ir_file.name}: ContentSchemas with invalid 'singular':\n{detail}"
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
        with open(ir_file) as f:
            ir_data = json.load(f)
        assert "ir_version" in ir_data, f"{ir_file.name}: missing ir_version"
        assert ir_data["ir_version"] == "0.5.0", (
            f"{ir_file.name}: expected ir_version '0.5.0', got '{ir_data['ir_version']}'"
        )

    @pytest.mark.parametrize(
        "ir_file",
        _ir_fixture_files(),
        ids=_ir_fixture_ids(),
    )
    def test_all_top_level_keys_are_known(self, ir_file):
        """No unexpected top-level keys (schema has additionalProperties: false)."""
        with open(ir_file) as f:
            ir_data = json.load(f)

        known_keys = {
            "ir_version", "reflection_enabled", "app_id",
            "name", "description", "auth",
            "content", "access_grants", "state_machines",
            "events", "routes", "pages", "nav_items", "streams",
            "computes", "channels", "boundaries",
            "error_handlers", "reclassification_points",
        }
        extra = set(ir_data.keys()) - known_keys
        assert not extra, (
            f"{ir_file.name}: unexpected top-level keys: {sorted(extra)}"
        )

    @pytest.mark.parametrize(
        "ir_file",
        _ir_fixture_files(),
        ids=_ir_fixture_ids(),
    )
    def test_content_names_are_qualified(self, ir_file):
        """Every Content 'name' must be a QualifiedName object with display/snake/pascal."""
        with open(ir_file) as f:
            ir_data = json.load(f)

        for i, content in enumerate(ir_data.get("content", [])):
            name = content.get("name")
            assert isinstance(name, dict), (
                f"{ir_file.name}: content[{i}].name is not an object"
            )
            for key in ("display", "snake", "pascal"):
                assert key in name, (
                    f"{ir_file.name}: content[{i}].name missing '{key}'"
                )

    @pytest.mark.parametrize(
        "ir_file",
        _ir_fixture_files(),
        ids=_ir_fixture_ids(),
    )
    def test_state_machine_content_refs_exist(self, ir_file):
        """Every state machine's content_ref must point to a defined Content."""
        with open(ir_file) as f:
            ir_data = json.load(f)

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
                f"{ir_file.name}: state_machine '{sm['machine_name']}' "
                f"references unknown content_ref '{ref}'. "
                f"Known: {sorted(all_names)}"
            )
