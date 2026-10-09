# Anolis provider executable profile v1 (organizational acceptance profile)

This document defines conventions the **Anolis runtime and tooling** expect of a
provider **binary**. It is an *organizational acceptance profile*, **not** part
of ADPP conformance: a binary can be fully ADPP-conformant (`semantics.md`) and
the framed-stdio profile while still diverging here.

Because these are conventions rather than protocol requirements, the conformance
harness marks them `executable_profile`, and a provider MAY waive an individual
expectation via its `--provider-profile` manifest (with an issue link), pending
a fix. Waivers may target **only** tests in this profile — never core ADPP or
framed-stdio (transport) tests.

## 1. CLI surface

- `--config <path>` — start the provider with the given config (the runtime
  launches the binary this way).
- `--version` — print a version string (containing a dotted `X.Y[.Z]` token) and
  exit `0`.
- `--check-config <path>` — validate a config without starting; exit `0` on a
  valid config.
- `--config-schema` — print the provider's config **JSON Schema** in a versioned
  envelope on stdout and exit `0`; **configless** (takes no `--config` — you use
  it to learn how to author config). See §2.
- `--check-host <path>` — check the host requirements a given config implies,
  print the result in a versioned envelope on stdout; exit `0` when none is
  unmet, `1` when any is. Read-only. See §6.

## 2. Config schema discovery (`--config-schema`)

`--config-schema` lets a client learn a provider's config contract **before** it
can author a config. Unlike a capability it is a **configless** CLI verb: a
provider never enters ADPP without a valid config, so a capability-advertised
schema would be unreachable when you need it. The schema is **provider-owned**
and emitted by the binary itself — version-matched to the code, no separate
artifact to drift. A third-party provider needs no protocol coordination to
satisfy this.

- Takes **no** `--config` (or any other arg). Writes a single JSON object to
  **stdout** and exits `0`; diagnostics, if any, go to stderr.
- The JSON is a thin **envelope** wrapping the config schema:

| Key | Status | Meaning |
| --- | --- | --- |
| `config_schema_version` | **required** | Integer ≥ 1 — the version of **this envelope convention** (this document defines `1`), **not** the version of the `schema` it carries. It lets the envelope evolve (new keys, changed semantics) independently of any provider's config schema. Modeled on `conformance_level`. Gated by the harness (waivable). |
| `schema` | **required** | A JSON object that is a **JSON Schema** for the provider's config. Content is provider-owned; the provider SHOULD declare its dialect via the schema's own `$schema` key (e.g. Draft 2020-12). The harness asserts shape, not content. |
| `provider` | recommended | Provider identity — the `provider_name` from the `--provider-profile` manifest / Hello — so a client can map a config to the binary that owns it. |

Provider-specific extra top-level keys are allowed. Only `config_schema_version`
and `schema` are gated; `provider` is a recommended convention (as with the §3
diagnostics keys).

Bumping `config_schema_version` signals an **envelope** change (new required
keys, changed semantics), independent of the provider's own config-schema
evolution. Versioning of the config schema *itself* is **provider-owned and not
standardized in v1** — a provider MAY encode it in the schema's `$id` (JSON
Schema has no standard version keyword); this silence is deliberate, not an
omission. Like `--provider-profile`, each provider owns its schema in its own
repo; the protocol never re-releases for a provider-specific schema.

## 3. Readiness diagnostics

When the provider advertises `supports_wait_ready=true`, a `WaitReady` response's
`diagnostics` map uses this standard key set (all values are strings):

| Key | Status | Meaning |
| --- | --- | --- |
| `init_time_ms` | **required** | Milliseconds spent initializing before ready — the key the runtime reads. Asserted by the harness (waivable). |
| `ready` | recommended | `"true"` / `"false"` — readiness as a value, pending a typed `ready` field in `readiness.proto`. |
| `device_count` | recommended | Number of devices the provider brought up. |
| `provider_impl` | recommended | Provider implementation identifier (e.g. name + version), for diagnostics. |
| `host_check` | recommended | `"ok"` / `"unmet"` — the startup result of the §6 host checks. |
| `host_unmet` | recommended | When `host_check` is `"unmet"`: a short summary of the unmet requirement ids and details, for an operator. |

Provider-specific extra keys are allowed. Only `init_time_ms` is gated; the
recommended keys are conventions, not asserted.

## 4. Process hygiene

- The provider MUST exit cleanly (code `0`) on stdin EOF.
- The provider MUST NOT write anything other than framed responses to stdout
  (stray bytes corrupt the frame stream — this is enforced by the framed-stdio
  profile, not waivable).

## 5. Capability conventions

Conventions for the capability surface (`CapabilitySet`) a device reports via
`DescribeDevice`. These keep ids predictable across providers and a future SDK;
they are conventions, not core ADPP, and are waivable.

- **`signal_id` is snake_case** — matches `^[a-z][a-z0-9_]*$` (a lowercase letter
  first, then lowercase letters, digits, underscores). No dots (`ph.value`), no
  camelCase. Asserted by `test_signal_ids_snake_case`.
- **`function_id` is per-type, numbered from 1** — within each device type the
  function ids are the contiguous set `{1..N}` for N declared functions. Not a
  global counter (`1001`, `1002`, …) and not an arbitrary value (`10`). Asserted
  by `test_function_ids_per_type_from_one`.

## 6. Host requirement check (`--check-host`)

A provider owns its transport, so only the provider knows what its transport
needs from the host: a device node present and accessible, a bus parameter
within a limit, an interface enabled. `--check-host` lets an installer or a
commissioning tool ask *before* starting the provider, and get an answer it can
print without understanding it. The requirements, their ids and their meaning are
**provider-owned**; tooling never interprets them.

- Takes the config path: `--check-host <path>`. What a provider needs depends on
  its config (which bus, which limits).
- **Read-only.** It MUST NOT actuate anything, and SHOULD avoid bus transactions:
  open and inspect the device, read configured parameters, do not talk to the
  hardware behind it.
- Writes a single JSON object to **stdout**; diagnostics, if any, go to stderr.
- Exit codes:

| Exit | Meaning |
| --- | --- |
| `0` | No requirement is `unmet` (each is `met` or `unknown`). |
| `1` | At least one requirement is `unmet`. |
| `2` | The provider could not evaluate its requirements, e.g. the config is invalid. Stdout MAY be empty. |

- The JSON is an **envelope** listing the requirements:

| Key | Status | Meaning |
| --- | --- | --- |
| `check_host_version` | **required** | Integer ≥ 1 — the version of **this envelope convention** (this document defines `1`). Gated by the harness (waivable). |
| `requirements` | **required** | Array of requirement objects (below). May be empty: a provider with nothing to check on this host (e.g. a mock config) reports `[]` and exits `0`. |
| `provider` | recommended | Provider identity, as for `--config-schema`. |

Each requirement object:

| Key | Status | Meaning |
| --- | --- | --- |
| `id` | **required** | Non-empty string, provider-owned (e.g. `bus.access`). Stable across releases so tooling can refer to it. |
| `status` | **required** | `"met"`, `"unmet"` or `"unknown"` (the provider cannot tell on this host — e.g. a parameter the platform does not expose). |
| `detail` | recommended | What was checked and found, in words an operator can act on. |
| `remedy` | recommended | For `unmet`: what to change on the host. Platform-specific advice belongs here, not in tooling. |

The exit code MUST agree with the statuses: `1` exactly when some requirement is
`unmet`. `unknown` does not fail the check: a requirement the provider cannot
observe on this platform must not block every install there. Provider-specific
extra keys are allowed, in the envelope and in each requirement.

A provider that does not implement the verb rejects it as a usage error: it
exits non-zero and prints no JSON on stdout (often nothing, sometimes a usage
message). The harness treats a non-zero exit without JSON on stdout as "not
implemented" and skips, so the convention adopts without coordination (as for
`--config-schema`).

**At startup** a provider runs the same checks. On an `unmet` requirement it
stays up and **not ready** rather than exiting, and reports what is unmet through
the §3 readiness diagnostics (`host_check`, `host_unmet`), so the runtime can show
why it has no devices from that provider.

## 7. Relationship to other documents

- `semantics.md` — core ADPP v1 (normative).
- `profiles/framed-stdio-v1.md` — the stdio transport binding (normative).
- This document — Anolis executable conventions (organizational; waivable).
