# Termin Presentation Provider Contract — Conformance Specification

**Version:** 0.9.0-draft (synthesized 2026-04-29)
**Status:** Draft — companion to BRD #2 (Presentation Provider System).
The conformance test pack at `tests/test_v09_presentation_provider.py`
is the executable form of this spec.

**Audience:** Three:

1. **Provider authors** writing a presentation provider that plugs
   into the reference runtime via the `PresentationProvider` Protocol
   (e.g., termin-spectrum-provider, termin-tailwind-default,
   termin-govuk-provider). Most consumers of this spec.
2. **Alternative runtime authors** building a Termin runtime that
   must accept providers written against the Protocol. The
   binding-resolver invariants in §3 are the most important section.
3. **App authors** writing source that uses contract packages
   (`Using "<ns>.<contract>"`) — knowing what the language guarantees
   when a provider is bound vs unbound tells them what their deploy
   config has to contain.

---

## 1. Scope

The presentation system has three concerns this spec covers:

- **The contract surface** — what a `PresentationProvider`
  implementation must declare and implement (§2).
- **Binding resolution** — how a deploy config's
  `bindings.presentation` map turns into runtime
  `(contract, product, instance)` triples, including namespace
  expansion and the default-Tailwind synthesis (§3).
- **Contract package loading + grammar extension** — how YAML
  packages declared in deploy config get loaded into a registry, how
  the parser's verb table is extended at parse time, and how
  cross-package verb collisions are rejected (§4).

Out of scope for v0.9: per-component override-mode dispatch (mixing
SSR Tailwind and CSR Spectrum within the same page); SSR rendering
through `PresentationProvider.render_ssr` (the legacy renderer path
is still authoritative). Both are tracked as v0.10+ work.

---

## 2. The Provider Contract

### 2.1 Required attributes

Every `PresentationProvider` implementation MUST expose:

- `declared_contracts: tuple[str, ...]` — the fully-qualified contract
  names this provider implements (e.g., `presentation-base.page`,
  `airlock-components.cosmic-orb`).
- `render_modes: tuple[Literal["ssr", "csr"], ...]` — at least one
  of `"ssr"` or `"csr"`. A provider that declares neither cannot be
  bound.

### 2.2 Required methods

- `render_ssr(contract, ir_fragment, data, principal_context) -> str`
  — invoked when `"ssr"` is in `render_modes`. Returns rendered HTML.
- `csr_bundle_url() -> Optional[str]` — invoked when `"csr"` is in
  `render_modes`. Returns the JS bundle URL the runtime injects into
  the page boot HTML. May return `None` for a provider that has not
  yet shipped a bundle (e.g., the Phase 5b.4 platform-only stub).

### 2.3 Tier-1 fallback

The reference Tailwind-default provider MUST register against every
contract in `presentation-base`. When a deploy config does not bind
`presentation-base`, a conforming runtime MUST synthesize the binding
to `tailwind-default` so the dispatch table is uniform across
explicit and implicit configs (§3.4).

---

## 3. Binding Resolution

### 3.1 Two deploy-config shapes

A conforming runtime MUST accept `bindings.presentation.<key>` and
`presentation.bindings.<key>` interchangeably — both produce the same
binding map.

### 3.2 Per-contract bindings

A binding keyed on a fully-qualified contract name
(`presentation-base.text`, `airlock-components.cosmic-orb`) targets
exactly that contract.

### 3.3 Namespace bindings

A binding keyed on a bare namespace name
(`presentation-base`, `airlock-components`) fans out to every
contract the namespace declares. For `presentation-base`, the ten
contracts in BRD #2 §5.1; for package namespaces, the contracts the
loaded YAML enumerates.

Per-contract bindings win over namespace bindings when both apply.

### 3.4 Default-Tailwind synthesis

When deploy config contains no binding for the `presentation-base`
namespace (and no per-contract binding for any
`presentation-base.*` key), a conforming runtime MUST synthesize a
default binding to product `tailwind-default`. The synthesis ensures:

- `ctx.presentation_providers` is uniform across the
  no-config and explicit-config paths.
- The bundle-discovery endpoint (`/_termin/presentation/bundles`)
  returns a stable shape.
- Conformance manifests (BRD §8.5) read a uniform set.

Explicit bindings always win over the synthesis.

### 3.5 Provider-instance caching

A factory invoked for product P with config C MUST be called exactly
once across the namespace fan-out. The single instance is bound
against every contract in the fan-out, not re-instantiated per
contract.

### 3.6 Unknown-product / unknown-namespace policy

A binding to a product that no provider has registered, or to a
namespace no contract package declares, MUST NOT crash the runtime.
The fan-out emits no triple for the unbound key. Deploy-time
`required_contracts` validation (BRD §8.5) is the fail-closed
surface for unresolved IR contracts.

---

## 4. Contract Package Loading

### 4.1 Deploy config shape

```yaml
contract_packages:
  - contract_packages/airlock-components.yaml
  - contract_packages/another-pkg.yaml
```

Each entry is a path to a YAML package file. Paths are resolved
relative to the deploy config's parent directory.

### 4.2 Required package fields

Per BRD #2 Appendix C, every package YAML MUST have:

- `namespace: <string>` — the bare namespace name (no dots).
- `version: <string>` — semver of the package.
- `contracts: [...]` — list of contract definitions.

Each contract definition MUST have a `name`. New-vocabulary contracts
(no `extends`) MUST have a non-empty `source-verb`. Override-mode
contracts (`extends: <ns>.<contract>`) MAY omit `source-verb`.

### 4.3 Verb collision

Two contracts in the same package with the same `source-verb` MUST
fail to load. Two packages declaring the same `source-verb` MUST
fail at registry-add time, with both colliding namespaces named in
the error message. v0.9 rejects collisions outright; v0.10+ may add
aliasing as a resolution path.

### 4.4 Fail-closed at startup

A deploy declaring a package that fails to load (missing file,
malformed YAML, verb collision) MUST fail at app startup. The runtime
cannot proceed with unresolvable `Using "<ns>.<contract>"` references
in source.

### 4.5 No packages declared is a no-op

Apps that use only `presentation-base` MUST be deployable with no
`contract_packages` field. The registry is `None` in that case;
binding resolution and fan-out work normally for the
`presentation-base` namespace.

---

## 5. Required Contracts Validation

(Forward-looking — full validation is BRD §8.5 work tracked for
v0.10. The IR side of the contract is in scope here.)

The lowered IR's `required_contracts` set MUST include:

- `presentation-base.page` for every page declared in source.
- `presentation-base.nav-bar` when a `Navigation bar:` block is
  present.
- `presentation-base.toast` / `.banner` for transition feedback
  declared in state machines.
- The qualified name of every contract-package source-verb instance
  in the source (e.g., `airlock-components.cosmic-orb`).

A conforming runtime MAY use this set to validate that every
required contract has a bound provider before starting; the
fail-closed behavior is reference-runtime-specific until v0.10.

---

## 6. Test Pack Coverage

The test pack at `tests/test_v09_presentation_provider.py` covers
the contracts in §2–§4 above. Pack scope: ~30 tests across:

- Provider Protocol shape verification (§2)
- Binding resolution (§3) — namespace fan-out, per-contract
  override, instance caching, default-Tailwind synthesis,
  unknown-product / unknown-namespace handling
- Contract package loading (§4) — well-formed package, missing
  required fields, intra-package verb collision, cross-package
  verb collision, deploy-config field validation, no-packages
  no-op, fail-closed semantics

Per BRD §12 / Q8, this pack lands as one commit (this commit) after
the underlying compiler slices (5c.1–5c.4) merge. Pack additions
(per-component dispatch, render-shape conformance) belong in v0.10+
when the underlying behavior ships.
