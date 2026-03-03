# Anolis Device Provider Protocol (ADPP) — v1

This directory defines the **Anolis Device Provider Protocol (ADPP)**, version **v1**.

ADPP specifies the **contract** between:

- **Anolis** — the orchestration and behavior runtime
- **Providers** — implementations that expose devices, signals, and callable functions

Providers may represent hardware backends such as:

- CRUMBS / I2C module buses
- Direct GPIO / SPI / I2C peripherals
- BLE-connected devices
- Simulated or replayed devices

ADPP is intentionally **transport-agnostic** and **language-agnostic**.

---

## Scope

ADPP v1 defines:

- Enumerating devices (`ListDevices`)
- Describing device capabilities (`DescribeDevice`)
- Reading telemetry signals (`ReadSignals`)
- Calling device functions (`Call`)
- Reporting provider and device health (`GetHealth`)
- Signaling provider startup readiness (`WaitReady`)

ADPP v1 explicitly does **not** define:

- Any specific transport (HTTP, gRPC, IPC, etc.)
- Authentication or authorization
- Time-series database schemas
- Behavior Tree semantics or execution rules

These concerns are handled by Anolis or deployment-specific infrastructure.

---

## Files

- `protocol.proto`  
  Normative Protobuf schema defining request/response messages.

- `semantics.md`  
  Normative behavioral semantics: roles, responsibilities, caching rules,
  error handling, framing guidance, and compatibility rules.

---

## Versioning

- The protocol is namespaced under `anolis.deviceprovider.v1`.
- Providers **MUST** report the protocol version they support.
- Breaking wire or semantic changes require a new major version directory
  (`v2`, `v3`, …).

Backward-compatible extensions (new fields, new optional messages) are
allowed within v1.

---

## Design principles

- **Language-agnostic**  
  Any language can implement a Provider by speaking ADPP.

- **Capability-first**  
  Providers describe _what devices can do_; Anolis binds behavior and UI to
  capabilities, not transports.

- **Provider owns mechanics**  
  Bus scanning, staged reads, retries, caching, and transport quirks are
  entirely provider-internal.

- **Anolis owns orchestration**  
  Modes, manual leases, arbitration, safety policies, and behavior execution
  are exclusively Anolis responsibilities.

ADPP exists to keep this boundary explicit and stable.
