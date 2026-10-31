# Anolis Device Provider Protocol (ADPP)

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

- Opening a session (`Hello`)
- Enumerating devices (`ListDevices`)
- Describing device capabilities (`DescribeDevice`)
- Reading telemetry signals (`ReadSignals`)
- Calling device functions (`Call`)
- Reporting provider and device health (`GetHealth`)
- Signaling provider startup readiness (`WaitReady`)

ADPP v1 explicitly does **not** define:

- Any specific transport (HTTP, gRPC, IPC, etc.); the framed stdio binding the
  Anolis runtime uses is a separate normative profile,
  `profiles/framed-stdio-v1.md`
- Authentication or authorization
- Time-series database schemas
- Behavior Tree semantics or execution rules

These concerns are handled by Anolis or deployment-specific infrastructure.

---

## Files

**Schema** (`proto/anolis/deviceprovider/v1/`):

- `envelope.proto` — `Request` / `Response` top-level envelopes
- `status.proto` — `Status` and error codes
- `handshake.proto` — `HelloRequest` / `HelloResponse`
- `inventory.proto` — `ListDevices` / `DescribeDevice`
- `telemetry.proto` — `ReadSignals` / `SignalValue`
- `call.proto` — `CallRequest` / `CallResponse`
- `health.proto` — `ProviderHealth` / `DeviceHealth`
- `readiness.proto` — `WaitReady` request/response
- `types.proto` — `Device`, `CapabilitySet`, `FunctionSpec`, `ArgSpec`
- `value.proto` — `Value`, `ValueType`

**Docs**:

- `semantics.md`  
  Normative behavioral semantics: roles, responsibilities, caching rules,
  error handling, framing guidance, and compatibility rules.
- `profiles/framed-stdio-v1.md`  
  The stdio transport binding: framing, the Hello metadata a provider
  advertises, and stdout/stderr use.
- `profiles/anolis-executable-profile-v1.md`  
  What an Anolis provider executable accepts on its command line, such as
  `--config` and `--check-host`.

---

## Versioning

- The protocol is namespaced under `anolis.deviceprovider.v1`.
- Providers **MUST** report the protocol version they support.
- Breaking **wire** changes require a new major version directory (`v2`, `v3`, …).
- **Semantic** tightening is introduced as an opt-in **conformance level** within
  the current major version, not a new directory — see `semantics.md`
  (_Conformance levels_) and `versioning.md`.

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
  Modes, arbitration of manual and automated calls, safety policies, and
  behavior execution are Anolis responsibilities. The spec also assigns manual
  leases to Anolis, but the runtime does not implement them and does not enforce
  `requires_lease` or `allowed_modes`. Providers may defensively reject unsafe
  device-level actions; Anolis does not rely on that.

ADPP exists to keep this boundary explicit and stable.
