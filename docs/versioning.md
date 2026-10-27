# Protocol Versioning Policy

## Scheme

This repository uses semantic versioning tags:

- `vMAJOR.MINOR.PATCH` (for example `v1.8.0`). Release asset names drop the `v`
  (`anolis-protocol-1.8.0-source.tar.gz`).

## Change Classification

- `PATCH`
  - Documentation fixes, non-functional clarifications, tooling updates.
  - No wire-contract changes.
- `MINOR`
  - Backward-compatible schema additions.
  - Typical example: adding optional fields with new field numbers.
- `MAJOR`
  - Breaking wire-contract changes.
  - Examples: removing fields, reusing field numbers, incompatible type/meaning changes.

## Conformance Changes (semantic contract)

A change can break the **conformance contract** (what a provider must do) without
touching the **wire contract** (the bytes on the stream). Tightening conformance
— a new `MUST` that can make a previously-conformant provider non-conformant — is
a breaking change to implementers even though `buf breaking` sees nothing. It is
**not** a silent `MINOR`/`PATCH`.

Such changes are introduced as a new, **opt-in conformance level** (`L2`, `L3`,
…; see `semantics.md`). Levels are **cumulative**: `Ln` requires `L1` plus every
clause tagged through `Ln`. A provider declares the level it targets in its
conformance manifest (`conformance_level`, default `1`) and SHOULD advertise it
in Hello metadata (`conformance_level`, absent ⇒ `1`).

**SemVer treatment:**

- **Introducing** a new optional level (documenting its clauses; the harness can
  test them once a provider opts in) is **MINOR** — existing L1 providers are
  unaffected.
- **Raising the minimum/default level** required of all `ADPP v1` providers is
  **breaking**: it must be a **major** release, or — preferably — it is never done
  globally, and consumers simply require a specific level of the providers they
  use.

**Enforcement.** The harness runs the requirements **up to the provider's declared
level**, all gating at that level, selected by a dedicated mechanism (a
`conformance_level(n)` marker driven by the manifest) — **not** the generic
`experimental` marker, which is reserved for genuinely unstable checks. A new
level's tests therefore gate immediately for a provider that declares it, and
never for one that does not; there is no global "graduation" event. The release
that first ships a level's tests is recorded in `CHANGELOG.md`.

Out-of-tree providers declare their target level the same way, adopting levels on
their own schedule rather than being broken by a harness bump.

## Proto Rules

- Never reuse removed or deprecated field numbers.
- Reserve removed field numbers and names.
- Keep package naming/versioning consistent with the current major contract.

## Enforcement

`buf breaking` is run on every PR against the `main` branch baseline.
A `buf breaking` failure fails CI. A major version bump is required only for
wire-contract-breaking changes (see Change Classification); a change that buf
flags but that keeps the wire format is classified MINOR. The release workflow
does not run `buf breaking`.

## Consumer Expectations

- Consumers pin explicit `anolis-protocol` versions.
- Consumer releases should document supported ADPP major version(s).
