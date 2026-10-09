# Changelog

All notable changes to the Anolis Device Provider Protocol (ADPP) are documented here.

## [Unreleased]

## [v1.8.0] — 2026-10-09

### Added

- **§6 host requirement check** (executable-profile, **waivable**). A provider
  may implement `--check-host <config>`: it checks the host requirements its
  config implies (a device node present and accessible, a bus parameter within a
  limit) and prints a versioned envelope (`check_host_version` + `requirements`,
  `provider` recommended); each requirement has a provider-owned `id`, a
  `status` of `met` / `unmet` / `unknown`, and recommended `detail` and `remedy`.
  Exit `0` when nothing is unmet (`unknown` does not fail), `1` when something
  is, `2` when it could not evaluate. Read-only. At startup a provider with unmet
  requirements stays up and not ready instead of exiting, reporting them through
  the new recommended readiness keys `host_check` and `host_unmet` (§3).
  Asserted by `test_cli_check_host`, which skips a provider that rejects the
  verb (non-zero exit and no JSON on stdout, where bread and ezo print their
  usage text), and validated hermetically by
  `test_selftest_check_host_envelope_validator` and
  `test_selftest_check_host_implemented`. Lets an installer or commissioning tool
  report a provider's host needs without knowing its transport
  (anolishq/anolis#318). Existing section numbers are unchanged; "Relationship
  to other documents" is now §7. No wire/proto change. (#66)

## [v1.7.0] — 2026-08-02

### Added

- **§2 config-schema discovery convention** (executable-profile, **waivable**).
  The executable profile defines a configless `--config-schema` verb: a compliant
  provider prints its config **JSON Schema** on stdout in a thin versioned
  envelope (`config_schema_version` + `schema`, `provider` recommended) and exits
  `0`. The schema is provider-owned and binary-emitted (version-matched, no
  separate artifact). Asserted by `test_cli_config_schema`, validated hermetically
  by `test_selftest_config_schema_envelope_validator`. Deliberately **not** an
  ADPP capability (a schema advertised over ADPP would be unreachable before a
  valid config exists) and — unlike a capability or the §7.3 gate — the harness
  **skips** a provider that does not yet implement the verb (it exits non-zero on
  the unrecognized flag), so no existing provider is turned red on upgrade and
  third-party providers need zero protocol coordination. Mirrors the
  `--provider-profile` ownership model (the provider owns its schema in its own
  repo; the protocol never re-releases for a provider-specific schema). No
  wire/proto change. (#62)

## [v1.6.0] — 2026-06-24

### Added

- **§7.3 freshness-hint gate** (core ADPP, non-waivable). `min_timestamp` is
  clarified as a hint that constrains *quality*, not *success*: a provider MUST
  NOT turn an otherwise-readable signal into an error (notably
  `CODE_DEADLINE_EXCEEDED`) solely because the freshness hint is unmet — it
  returns `CODE_OK` with best-available values (`test_min_timestamp_hint_is_not_fatal`,
  validated hermetically by `test_selftest_freshness_hint_validator`). No
  wire/proto change. Closes a silent-divergence surface ahead of the
  provider-SDK extraction (anolis-protocol#47); a provider that errored on an
  unmet hint becomes non-conformant when it bumps to the harness release
  carrying this test.

## [v1.5.0] — 2026-06-23

No wire/proto changes from v1.4.0 — this release is conformance-harness and
specification only. Providers upgrade by bumping the harness pin; generated code
is unaffected.

### Added

- **Bucket C — capability conventions** (executable-profile, **waivable**). The
  executable profile now settles two naming conventions, asserted by the harness
  and waivable via a provider's profile:
  - **`signal_id` is snake_case** (`^[a-z][a-z0-9_]*$`) — `test_signal_ids_snake_case`.
  - **`function_id` is per-type, numbered from 1** — within each device type the
    declared function ids form the contiguous set `{1..N}` —
    `test_function_ids_per_type_from_one`.
- **WaitReady standard diagnostics key set.** When a provider advertises
  `supports_wait_ready=true`, the `WaitReady` response `diagnostics` map uses a
  standard key set; `init_time_ms` is **required and gated** (waivable, the key
  the runtime reads), other keys are recommended conventions. (#39)
- **Gated default-signal-set and call-results assertions** (closes the
  harness-coverage item #41):
  - **§7.2** — an empty-`signal_ids` read on a device that declares signals must
    return a non-empty subset of the declared signals
    (`test_default_read_returns_declared_subset`).
  - **§8.1** — a synchronous successful call to a function that declares results
    must populate `CallResponse.results`
    (`test_call_declared_results_are_populated`). (#42)

### Changed

- **`docs/semantics.md` clarifications** backing the new gates (no behavior
  change for compliant providers): §7.2 now requires a *non-empty* default
  signal set for any device type declaring ≥1 signal; §8.1 now requires a
  synchronous successful call to populate its declared results. (#42)

## [v1.4.0] — 2026-06-21

### Added

- **Conformance level 2 (opt-in).** The harness gains a cumulative,
  provider-declared level model: a provider names its level in its manifest
  (`conformance_level`, default `1`) and SHOULD advertise it in Hello metadata.
  Tests are gated by a `conformance_level(n)` marker; a provider runs the
  requirements **up to** the level it declares, and a declared level above what
  the harness implements is rejected. Introducing L2 does not affect existing L1
  providers.
  - **[L2] semantics** (`docs/semantics.md`, tagged `[L2]`): a request before
    Hello → `CODE_FAILED_PRECONDITION` (§3.2); declared numeric bounds are
    inclusive and a value outside them → `CODE_OUT_OF_RANGE`, a non-finite double
    → `CODE_INVALID_ARGUMENT` (§8.3); deadlines advertised via the
    `supports_deadlines` Hello key — expired → `CODE_DEADLINE_EXCEEDED`, malformed
    → `CODE_INVALID_ARGUMENT` (§8.4); every `CODE_OK` `SignalValue` carries a valid
    `timestamp` and a defined non-`UNSPECIFIED` `quality` (§7.1).
  - **L2 conformance tests** (`test_l2.py`) covering all of the above, with
    valid-argument synthesis and bound isolation; an L1 provider never runs them.
- **Bucket-A positive-call coverage** (L1): a no-required-argument call (by id and
  by name) is accepted; a missing required argument → `CODE_INVALID_ARGUMENT`;
  `function_id` is preferred over `function_name` when both are given (§6.2).

### Changed

- `docs/versioning.md`: documents that **semantic** tightening (a stricter `MUST`
  with the wire unchanged) is a conformance break, handled via opt-in conformance
  levels — introducing a level is MINOR, raising the global minimum is breaking.
  `README.md` and `docs/index.md` reconciled to one wire-vs-semantic model.

### Notes

- **No wire-contract change** — the proto schema is identical to v1.3.0. This is an
  additive harness + semantics release; the new conformance level is opt-in, so no
  existing (L1) provider is affected. Versioned MINOR.

## [v1.3.0] — 2026-06-20

### Added

- **Cross-provider ADPP conformance harness**, shipped in the wheel (#26): a
  generic verifier that drives any provider binary through the ADPP v1 wire
  lifecycle and asserts compliance. Adds a `[conformance]` optional-dependency
  extra and the `anolis-adpp-conformance` console script. Providers pull this
  versioned artifact and supply their own identity/config/waivers via
  `--provider-profile`; the contract ships **no implementer-specific data**.
- **Normative profile docs** that give the harness's transport/executable
  requirements an authority (so conventions don't become protocol law via tests
  alone):
  - `docs/profiles/framed-stdio-v1.md` — the stdio transport binding
    (`uint32_le` framing, 1 MiB frame cap, Hello metadata, malformed-stream
    behavior and exit codes). This is the named "mutual agreement" that
    `semantics.md` §2 leaves to a binding.
  - `docs/profiles/anolis-executable-profile-v1.md` — Anolis executable
    conventions (an organizational acceptance profile, **not** ADPP).

### Fixed

- `handshake.proto`: corrected the `protocol_version` comment (`"1"` → `"v1"`,
  the value the runtime and every provider actually require).

### CI

- Add CI OK aggregator gate: removed `paths-ignore`, added `dorny/paths-filter`
  to detect code-vs-docs changes, gated all jobs behind the filter, and added a
  final `ok` job as the sole required status check for `main` branch protection.
- Add a hermetic conformance lane on Python 3.10 + 3.12: verifier self-tests
  against in-repo fake providers, a plugin-isolation regression, and a
  misconfiguration gate (a misused invocation must exit non-zero, never green).

### Notes

- **No wire-contract change** — the proto schema is identical to v1.2.0. This is
  an additive packaging/tooling + docs release; versioned MINOR to signal the
  new conformance-harness capability shipped in the wheel.

## [v1.2.0] — 2026-04-24

### Added

- `ArgSpec` bounds fields (`min_double`, `max_double`, `min_int64`, `max_int64`,
  `min_uint64`, `max_uint64`) are now declared `optional` in proto3.

  This gives each field **explicit presence** — consumers gain `has_min_double()`,
  `has_max_double()`, etc. accessor methods. A bound explicitly set to `0` is now
  distinguishable from a bound that was never set.

  **Wire format is unchanged.** Field numbers and encoding are identical to v1.1.4.
  Old senders and new receivers interoperate correctly; old receivers see `0` as
  the field value when new senders set an explicit zero, which matches prior behaviour.

  **Buf breaking check:** This change alters the field's presence semantics (implicit →
  explicit) which `buf breaking --use FILE` flags as a cardinality change. It is a
  deliberate, wire-backward-compatible enhancement and constitutes a MINOR version bump
  per the ADPP versioning policy.

### Migration

Consumers that previously used a non-zero heuristic to detect whether a bound was set
(`min != 0 || max != 0`) should replace that logic with `has_min_*()` / `has_max_*()`
calls after updating their FetchContent URL to the v1.2.0 source tarball.

Consumers that do not call any bound-presence logic require no source changes — all
existing `set_min_*()` and `set_max_*()` calls continue to compile and behave as before.

## [v1.1.4] — 2025-11-10

Initial public release with full ADPP v1 message definitions.
