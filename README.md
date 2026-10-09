# anolis-protocol

[![buf](https://github.com/anolishq/anolis-protocol/actions/workflows/buf.yml/badge.svg)](https://github.com/anolishq/anolis-protocol/actions/workflows/buf.yml)

Canonical protocol contracts for the Anolis ecosystem.

## Quick Start

### Consume a pinned release (recommended)

**C++ (CMake FetchContent):**

```cmake
include(FetchContent)
FetchContent_Declare(
    anolis_protocol
    URL https://github.com/anolishq/anolis-protocol/releases/download/v1.8.0/anolis-protocol-1.8.0-source.tar.gz
    URL_HASH SHA256=1823afe8ee750575a23043ce1757e5a859a571bdffd953ba42675a951967d215
)
FetchContent_MakeAvailable(anolis_protocol)
# proto files are at ${anolis_protocol_SOURCE_DIR}/proto/
```

Replace the version and hash from the [latest release](https://github.com/anolishq/anolis-protocol/releases/latest) `SHA256SUMS` file.

**Python (wheel from the GitHub Release):**

Each tagged release attaches a built wheel (generated protobuf bindings) to the [GitHub Release](https://github.com/anolishq/anolis-protocol/releases/latest) (there is no PyPI publish). Pin it by URL:

```sh
pip install "anolis-protocol @ https://github.com/anolishq/anolis-protocol/releases/download/v1.8.0/anolis_protocol-1.8.0-py3-none-any.whl"
```

The cross-provider **conformance harness** (the `[conformance]` extra + the
`anolis-adpp-conformance` script) ships in the wheel from **v1.3.0** onward
(releases up to and including v1.2.0 predate it):

```sh
pip install "anolis-protocol[conformance] @ https://github.com/anolishq/anolis-protocol/releases/download/v1.8.0/anolis_protocol-1.8.0-py3-none-any.whl"
# or, from a checkout: pip install ".[conformance]"
```

**buf BSR (code generation):**

```yaml
# buf.yaml deps
deps:
  - buf.build/anolishq/anolis-protocol
```

### Work with the schema directly (contributors)

Requires [Buf CLI](https://buf.build/docs/installation) v1.x.

```bash
# Verify schema compiles
buf build

# Lint
buf lint

# Check breaking changes vs main
buf breaking --against "https://github.com/anolishq/anolis-protocol.git#branch=main"

# Generate C++ and Python bindings (outputs to gen/, not committed)
buf generate
```

- Owns ADPP protobuf schema used by `anolis` and providers.
- Contains the protocol contract (schema + normative semantics/profile docs) plus
  the generic **conformance harness** that verifies any provider against it.
- Contains **no provider/runtime implementation code** — the harness is a generic
  verifier, and it ships no knowledge of any specific provider.

## Layout

```text
anolis-protocol/
├── buf.yaml              # Buf v2 module config (lint, breaking, deps)
├── buf.gen.yaml          # Canonical generation config (C++, Python)
├── buf.lock              # Pinned dependency hashes
├── proto/
│   └── anolis/
│       └── deviceprovider/
│           └── v1/
│               ├── envelope.proto    # Request / Response top-level envelopes
│               ├── status.proto      # Status and error codes
│               ├── handshake.proto   # Hello request/response
│               ├── inventory.proto   # ListDevices / DescribeDevice
│               ├── telemetry.proto   # ReadSignals / SignalValue
│               ├── call.proto        # CallRequest / CallResponse
│               ├── health.proto      # ProviderHealth / DeviceHealth
│               ├── readiness.proto   # WaitReady request/response
│               ├── types.proto       # Device, CapabilitySet, FunctionSpec, ArgSpec
│               └── value.proto       # Value, ValueType
├── conformance/            # generic ADPP conformance harness (shipped in the wheel)
│   ├── anolis_conformance/ # AdppClient, spec, checks, the three contract suites
│   └── ADPP-CONFORMANCE.md # how to run it (non-normative)
└── docs/
    ├── index.md
    ├── semantics.md        # core ADPP v1 (normative)
    ├── profiles/
    │   ├── framed-stdio-v1.md            # stdio transport binding (normative)
    │   └── anolis-executable-profile-v1.md  # Anolis executable conventions
    └── versioning.md
```

## Development

Requires [Buf CLI](https://buf.build/docs/installation) v1.x.

```bash
# Verify the schema compiles
buf build

# Check lint rules
buf lint

# Check formatting
buf format --diff

# Check for breaking changes vs main
buf breaking --against "https://github.com/anolishq/anolis-protocol.git#branch=main"

# Generate C++ and Python bindings (outputs to gen/, not committed)
buf generate
```

## Versioning

- Repository uses semantic versioning tags: `MAJOR.MINOR.PATCH`.
- Breaking **wire-contract** changes require a major bump (`buf breaking`
  enforces this on every PR).
- **Semantic** tightening (stricter conformance, same wire) ships as an opt-in
  **conformance level**, not a silent minor — see `docs/versioning.md`
  (*Conformance Changes*).
- See `docs/versioning.md`.

## Future Work

- long-term: add `CMakeLists.txt` + cmake config; cut consumers to `find_package` — defer until FetchContent causes pain
