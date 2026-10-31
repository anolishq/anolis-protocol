# ADPP v1 Semantics (normative)

This document defines the **normative semantics** of the
**Anolis Device Provider Protocol (ADPP)** v1.

> **Conformance levels.** A provider's conformance is stated as `ADPP v1/L<n>` —
> the v1 wire contract plus a **cumulative** semantic bar. **Level 1** (L1) is
> everything in this document *not* tagged. **Level 2** (L2) is
> L1 **plus** every requirement tagged **[L2]**; further levels are likewise
> additive. The wire contract is identical across levels — a level only *tightens*
> behavior.
>
> Levels are **opt-in**. A provider **declares** its level in its conformance
> manifest (`conformance_level`, **default 1**) and SHOULD advertise it in Hello
> metadata (`conformance_level`, **absent ⇒ 1**). The conformance harness runs
> the requirements **up to the declared level** — all gating at that level (there
> is no separate non-gating phase). Introducing a new level does **not**
> invalidate lower-level providers; a plain "`ADPP v1` conformant" claim means
> **at least L1**. Raising the *minimum* level required of all `ADPP v1`
> providers is a breaking change — see `versioning.md`.
>
> When a provider both advertises `conformance_level` in Hello metadata **and**
> declares one in its manifest, the two MUST agree, and the value MUST be a level
> the verifier implements. A verifier MUST reject a declared level it does not
> implement rather than silently testing a lower bar.

---

## 1. Roles and responsibilities

### 1.1 Anolis (client)

Anolis is the ADPP client. It is responsible for:

- Orchestrating machine behavior (e.g., Behavior Trees)
- Arbitrating manual vs autonomous control
- Enforcing safety policies and operating modes
- Persisting telemetry, state, and events
- Exposing external APIs (HTTP, dashboards, etc.)

### 1.2 Provider (server)

A Provider is an ADPP server that exposes devices backed by some implementation
(I2C/CRUMBS, GPIO, BLE, simulation, etc.).

A Provider is responsible for:

- Discovering and reporting devices (when applicable)
- Describing device capabilities (functions and signals)
- Executing reads and calls
- Managing backend-specific mechanics:
  - staged reads
  - caching
  - retries and backoff
  - bus scanning and filtering
- Reporting provider and device health

**Providers MUST NOT encode orchestration policy.**

Providers may defensively validate inputs and reject invalid or unsafe
device-level actions, but Anolis is the sole authority for:

- Control modes (`MANUAL`, `AUTO`, `IDLE`, `FAULT`)
- Manual control leases (v1 has only the per-function hint
  `FunctionPolicy.requires_lease`; the Anolis runtime does not implement leases)
- Cross-device safety interlocks
- Behavior execution semantics

---

## 2. Transport and framing

ADPP messages are defined in `proto/anolis/deviceprovider/v1/envelope.proto`
using `Request` and `Response` envelopes.

ADPP itself is transport-agnostic. When used over a byte-stream transport
(recommended for local IPC):

- Each message MUST be framed using a length prefix followed by serialized
  Protobuf bytes.
- The length prefix SHOULD be:
  - an unsigned varint, or
  - a fixed-width 32-bit unsigned integer,
    by mutual agreement.
- Implementations MUST handle fragmentation and coalescing
  (a stream may deliver partial or multiple frames).

Rationale: Protobuf does not define framing; length-prefixed framing is a
well-established pattern.

The Anolis runtime's concrete binding of this agreement — fixed `uint32_le`
framing, the frame-size limit, Hello metadata, and malformed-stream behavior — is
specified normatively in `profiles/framed-stdio-v1.md`.

---

## 3. Session handshake

### 3.1 Hello

- The client SHOULD send `HelloRequest` as the first message.
- The provider MUST respond with `HelloResponse`.
- The client MUST validate `HelloResponse.protocol_version` matches the requested protocol version and fail session setup if it does not.
- If the requested `protocol_version` is not supported, the provider MUST
  respond with:
  - `CODE_FAILED_PRECONDITION`, or
  - `CODE_UNIMPLEMENTED`.

### 3.2 Requests before Hello

- **[L2]** A provider that receives any request other than `HelloRequest`
  before a successful Hello exchange MUST reject it with
  `CODE_FAILED_PRECONDITION` and MUST NOT process it. (The client SHOULD send
  Hello first per §3.1; this defines the provider's behavior if it does not.)

---

## 4. Request / response correlation

- `request_id` MUST be unique per in-flight request within a session.
- Providers MUST echo the same `request_id` in the corresponding `Response`.
- Providers MAY process requests concurrently.
- Responses MAY arrive out of order.

Clients MUST correlate responses using `request_id` and MUST NOT assume
ordering.

---

## 5. Inventory and identity

### 5.1 Device identity

- `Device.device_id` MUST be stable for the lifetime of the Provider process.
- Providers SHOULD preserve `device_id` stability across restarts when feasible.
- Uniqueness is scoped to the Provider; Anolis SHOULD treat
  `{provider_id, device_id}` as globally unique, where `provider_id` is the
  client's configured name for the provider instance (e.g. `sim0`), not the
  provider's self-reported `provider_name`.

### 5.2 Discovery

- Providers MAY support discovery (e.g., scanning an I2C bus).
- `ListDevices` MUST return the currently known devices.
- Non-discoverable backends MAY return a static set or an empty list.

### 5.3 Backend filtering

All bus scanning, filtering, probing, or identification logic is
**provider-internal**.

Example: a CRUMBS Provider may scan all I2C addresses and only report devices
that respond to a CRUMBS identify handshake.

---

## 6. Capabilities

### 6.1 DescribeDevice

- `DescribeDevice` MUST return the complete `CapabilitySet` for the device.
- Function IDs and signal IDs MUST be stable for a given device type/version.

### 6.2 Function identifiers

- `function_id` is the preferred stable identifier.
- `function_name` is a human-readable convenience.
- If both are provided in a `CallRequest`, the provider MUST prefer
  `function_id`.

### 6.3 Policy metadata

`FunctionPolicy` fields describe when and how a function may be called. Anolis
is the authoritative enforcer.

In v1:

- `allowed_modes` and `min_interval_ms` are enforced by Anolis runtime releases
  after 0.5.0 (anolishq/anolis#566). A call in a mode outside a non-empty
  `allowed_modes`, or sooner than `min_interval_ms` after the last call
  dispatched to that function, is refused with `CODE_FAILED_PRECONDITION`, and
  never reaches the provider. The runtime's own safe-state calls (its software
  stop and startup safe state) are exempt from both. Earlier releases read
  neither.
- Leases are not implemented. `requires_lease` is reported to clients, and the
  runtime logs a warning at discovery and calls the function without a lease. A
  provider MUST NOT rely on `requires_lease` for exclusive access.
- Providers MAY defensively reject calls that violate policy metadata, but
  Anolis MUST NOT rely on provider enforcement.

---

## 7. Telemetry reads

### 7.1 ReadSignals behavior

- Providers MAY return cached values, live values, or a combination.
- **[L2]** In a `CODE_OK` `ReadSignalsResponse` — including the partial-success
  form of §7.4 — every `SignalValue` MUST set `timestamp` (field present, a valid
  `google.protobuf.Timestamp` at the observation time) and MUST set `quality` to
  a value defined by the current schema other than `QUALITY_UNSPECIFIED`. Error
  responses carry no telemetry and are exempt. *(Level 1: `timestamp` was SHOULD;
  `quality` was not mandated.)*
- If a value exceeds `SignalSpec.stale_after_ms`, providers SHOULD report
  `QUALITY_STALE`.

### 7.2 Default signals

For any device type that declares at least one signal, a provider MUST define a
**stable, non-empty subset of signals** designated as **default signals**.

- Default signals are returned when `ReadSignalsRequest.signal_ids` is empty.
- A default read (empty `signal_ids`) on a device that declares signals MUST
  therefore return a non-empty set of values whose `signal_id`s are a subset of
  the declared signals. (The subset is provider-curated and need not be the full
  declared set.)
- Default signals SHOULD represent low-cost, routinely useful telemetry
  suitable for dashboards and polling loops.
- Expensive or rarely-used signals SHOULD NOT be default.

This requirement ensures predictable behavior across providers.

*How the Anolis runtime polls (non-normative):* it does not poll the default
signals. It polls, by explicit `signal_ids`, every signal whose
`SignalSpec.poll_hint_hz` is above 0, at its own configured interval, and
serves device state only from those reads. A signal with `poll_hint_hz` 0 is
never polled and does not appear in the runtime's state. A provider meant for
Anolis sets a positive `poll_hint_hz` on every signal it wants shown.

### 7.3 Freshness hints

If `ReadSignalsRequest.min_timestamp` is provided:

- Providers SHOULD attempt to satisfy the freshness requirement.
- If not feasible, providers SHOULD return the best available values and
  indicate staleness via `quality` and/or `Status.details`.
- `min_timestamp` is a **hint that constrains quality, not success**: a provider
  MUST NOT treat an unmet freshness hint as a hard deadline. An otherwise-
  readable signal MUST NOT, on account of the hint alone, be turned into an error
  response (notably `CODE_DEADLINE_EXCEEDED`); the read returns `CODE_OK` with the
  best available values. (A genuine read failure may still return
  `CODE_UNAVAILABLE` etc.) *(Clarification: previously unstated; a provider that
  returned an error solely because the hint was unmet is non-conformant under
  this rule.)*

### 7.4 Missing signals

If a requested signal is unknown, providers MUST choose one consistent
behavior:

- Fail the request with `CODE_NOT_FOUND`, **or**
- Return partial results and omit unknown signals.

(Recommended for v1: fail with `CODE_NOT_FOUND` to simplify client logic.)

---

## 8. Function calls

### 8.1 Execution model

- Providers MAY implement calls synchronously.
- Providers MAY accept calls asynchronously and return an `operation_id`.

ADPP v1 does not define an operation lifecycle API. If async calls are used,
providers MUST document how results are observed (typically via signals).

(Recommended for v1: synchronous execution.)

When a function declares results (`FunctionSpec.results`), a **synchronous**
successful call (`CODE_OK` with no `operation_id`) MUST populate
`CallResponse.results`, keyed by the declared `ArgSpec.name`s — a provider that
declares results MUST NOT return an empty result map for a completed call.
Asynchronous acceptance (`CODE_OK` with `operation_id` set) observes results
later (per above), so it carries no such obligation.

### 8.2 Idempotency

- `idempotency_key` is an optional retry hint.
- Providers MAY ignore it in v1.
- If honored, providers SHOULD treat repeated calls with the same key as safe
  replays.

### 8.3 Validation

Providers MUST validate device existence, function existence, required
arguments, argument types, and declared numeric bounds.

**Status codes by category:**

- An unknown **device** identifier, or the **selected function identifier** (the
  `function_id` when nonzero, otherwise the resolved `function_name`), →
  `CODE_NOT_FOUND` (all levels). When `function_id` is nonzero, `function_name`
  is not selected and is not validated (it is ignored per §6.2).
- A value outside its declared bounds:
  - **L1:** → `CODE_INVALID_ARGUMENT` **or** `CODE_OUT_OF_RANGE`.
  - **[L2]:** → MUST be `CODE_OUT_OF_RANGE`.
  L2 only *tightens* the L1 choice, so an L2 provider also satisfies L1 — the
  levels stay cumulative.
- Every other invalid input (wrong type, missing required argument) →
  `CODE_INVALID_ARGUMENT` (all levels).

**Numeric value rules ([L2]):**

- Declared numeric bounds (`ArgSpec.min_*` / `ArgSpec.max_*`) are **inclusive**:
  a value equal to a bound is valid; a value strictly outside is out of range.
- A `VALUE_TYPE_DOUBLE` argument that carries a declared bound MUST be finite. A
  non-finite value (`NaN`, `+Inf`, `-Inf`) is malformed input and MUST be
  rejected with `CODE_INVALID_ARGUMENT`. This finiteness check **precedes** the
  bound check — so `+Inf` is `CODE_INVALID_ARGUMENT`, never `CODE_OUT_OF_RANGE`,
  even though it numerically exceeds any maximum.

### 8.4 Deadlines

Deadline support is the **[L2]** deadline capability contract. A provider
advertises it via the Hello metadata key `supports_deadlines` (`"true"` /
`"false"`; **absent ⇒ `"false"`**). At L1, deadline behavior is unconstrained: a
provider MAY ignore `CallRequest.deadline` entirely, and `supports_deadlines`
carries no obligation. An L2 provider that advertises `supports_deadlines="true"`
takes on the contract below; the deadline then applies to **every** call it
accepts:

- **[L2]** A malformed `deadline` (not a valid `google.protobuf.Timestamp`) →
  `CODE_INVALID_ARGUMENT`.
- **[L2]** If the deadline is **already expired** when the request is validated,
  the provider MUST return `CODE_DEADLINE_EXCEEDED` and MUST NOT invoke the
  function (no side effects).
- **[L2]** If the deadline expires **during synchronous execution**, the provider
  MUST make a documented best-effort to cancel and MUST return
  `CODE_DEADLINE_EXCEEDED`. Because physical actuation can be irreversible once
  issued, side effects MAY have occurred; the provider SHOULD report what is
  known via `Status.details`. "Abort" here is best-effort, not a guarantee of no
  effect.

**`CODE_OK` means done — except for accepted async calls.** A provider MUST NOT
report `CODE_OK` for **synchronous** work it did not complete. For an
**asynchronous** call (§8.1), `CODE_OK` with `CallResponse.operation_id`
populated means the call was **accepted** (not yet complete); for such calls the
deadline governs *acceptance*, and results are observed later (typically via
signals). This preserves §8.1.

---

## 9. Health reporting

### 9.1 Provider health

- `GetHealth` MUST return `ProviderHealth`.
- `ProviderHealth.state` reflects the provider’s overall ability to service
  requests.

### 9.2 Device health

- `DeviceHealth` reflects reachability and freshness.
- `last_seen` SHOULD be updated whenever the provider successfully communicates
  with the device backend.

---

## 10. Error handling

- Every `Response` MUST include a `Status`.
- `CODE_OK` indicates success.
- Errors SHOULD include a human-readable message.
- `Status.details` MAY include structured diagnostic metadata.

---

## 11. Backward compatibility

- Unknown fields MUST be ignored (standard Protobuf behavior).
- New optional fields may be added within v1.
- Incompatible **wire** changes require a new major version (`v2`).
- **Semantic** tightening (a stricter `MUST`) is introduced as a new, **opt-in
  conformance level** within the current major version (see the *Conformance
  levels* note above and `versioning.md`). Current practice departs from that
  rule: a requirement classified as a clarification is added untagged at L1 and
  gated by the L1 harness, even where it can make a previously-conformant
  provider non-conformant (as §7.3 can). §7.2 (non-empty default set), §7.3
  (freshness hint) and §8.1 (declared results) are such clauses. Raising
  the *minimum* level required of all `ADPP v1` providers is itself a breaking
  change and requires a major version.

---

## 12. Security considerations (non-normative)

ADPP v1 does not define authentication.

For local IPC, rely on OS-level permissions (e.g., Unix socket ownership).
For network transports, ADPP SHOULD be wrapped in an authenticated and
encrypted channel appropriate to the deployment.
