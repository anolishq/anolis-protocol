# Changelog

All notable changes to the Anolis Device Provider Protocol (ADPP) are documented here.

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
