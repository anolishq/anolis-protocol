# ADPP framed-stdio profile v1 (normative)

This document is **normative** for providers that speak ADPP v1 over a stdio
byte stream. It is the named "mutual agreement" that `semantics.md` §2 leaves to
a transport binding: core ADPP is transport-agnostic; this profile pins the one
binding the Anolis runtime uses. Core message/status/correlation semantics remain
governed by `semantics.md`.

A provider advertises that it implements this profile via its Hello metadata
(below). The conformance harness's framed-stdio suite asserts exactly the
requirements here.

## 1. Framing

- Each ADPP `Request`/`Response` MUST be framed as a **4-byte little-endian
  unsigned integer length prefix** (`uint32_le`) followed by exactly that many
  bytes of serialized Protobuf. This is the fixed-width-32 option of
  `semantics.md` §2.
- The transport is the provider's **stdin** (requests) and **stdout**
  (responses). Nothing other than framed responses may be written to stdout;
  diagnostics go to stderr.
- Implementations MUST handle fragmentation and coalescing — a read may deliver a
  partial frame or several frames at once (`semantics.md` §2).

## 2. Frame size limit

- The maximum frame length is **1 MiB (1048576 bytes)**, enforced in both
  directions.
- A length prefix that exceeds the limit MUST be rejected (the receiver MUST NOT
  attempt to allocate or read it).

## 3. Hello metadata

A provider implementing this profile MUST advertise in `HelloResponse.metadata`:

| Key | Value |
| --- | --- |
| `transport` | `stdio+uint32_le` |
| `max_frame_bytes` | `1048576` |
| `supports_wait_ready` | `true` or `false` |

Providers MAY advertise additional metadata keys.

## 4. Malformed-stream behavior

On a malformed, unparseable, oversized, or otherwise garbage frame, a provider
MUST react in a **controlled** way — one of:

- emit a well-formed framed `Response` carrying a **defined error** `Status`
  (not `CODE_OK`, not `CODE_UNSPECIFIED`); or
- terminate cleanly with one of the documented exit codes:
  - `0` — clean EOF / shutdown,
  - `2` — frame/read error,
  - `3` — parse error.

A provider MUST NOT, on malformed input:

- crash (terminate via a signal — a negative wait status);
- hang (neither respond nor exit);
- emit an over-cap or unparseable response;
- emit a response and then exit with an undocumented code;
- exit with any code other than `0`/`2`/`3`.

## 5. Relationship to other documents

- `semantics.md` — core ADPP v1 (normative; messages, status, correlation,
  read/call semantics).
- `profiles/anolis-executable-profile-v1.md` — Anolis executable conventions
  (an organizational acceptance profile, **not** ADPP conformance).
- [`conformance/ADPP-CONFORMANCE.md`](https://github.com/anolishq/anolis-protocol/blob/main/conformance/ADPP-CONFORMANCE.md)
  — the executable harness and how to run it (non-normative; it asserts the
  documents above).
