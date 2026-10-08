"""Reusable conformance assertions.

Factored out of the test modules so the verifier self-tests can exercise the
*real* validation logic against deliberately-faulty fake providers — rather than
a reimplementation that could drift from what the suite actually enforces.
"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace

from . import spec
from .client import AdppClient, ProviderHang


class ConformanceFailure(AssertionError):
    """A provider violated a conformance requirement."""


def assert_status_present(response) -> None:
    """Every Response MUST carry a Status (semantics.md §10)."""
    if not response.HasField("status"):
        raise ConformanceFailure("response is missing the required Status (semantics.md §10)")


# QUALITY_UNSPECIFIED is 0 in the proto enum (proto3 default).
_QUALITY_UNSPECIFIED = 0
# Valid google.protobuf.Timestamp range (0001-01-01 .. 9999-12-31, UTC).
_TS_MIN_SECONDS = -62135596800
_TS_MAX_SECONDS = 253402300799


def assert_signalvalues_l2(read_response) -> None:
    """semantics.md §7.1 [L2]: in a CODE_OK ReadSignalsResponse every SignalValue
    MUST set a **valid** ``timestamp`` and a ``quality`` that is a **defined**
    enum value other than ``QUALITY_UNSPECIFIED``. Caller checks the status is OK
    first."""
    for value in read_response.read_signals.values:
        sid = value.signal_id
        if not value.HasField("timestamp"):
            raise ConformanceFailure(f"signal {sid!r}: [L2] requires a timestamp on OK values")
        ts = value.timestamp
        if not (0 <= ts.nanos <= 999_999_999):
            raise ConformanceFailure(
                f"signal {sid!r}: timestamp.nanos {ts.nanos} is not in [0, 1e9)"
            )
        if not (_TS_MIN_SECONDS <= ts.seconds <= _TS_MAX_SECONDS):
            raise ConformanceFailure(
                f"signal {sid!r}: timestamp.seconds {ts.seconds} is outside the valid range"
            )
        valid_qualities = set(value.DESCRIPTOR.fields_by_name["quality"].enum_type.values_by_number)
        if value.quality not in valid_qualities:
            raise ConformanceFailure(
                f"signal {sid!r}: quality {value.quality} is not a value defined by the schema"
            )
        if value.quality == _QUALITY_UNSPECIFIED:
            raise ConformanceFailure(f"signal {sid!r}: quality must not be QUALITY_UNSPECIFIED")


def assert_freshness_hint_not_fatal(read_response, codes: SimpleNamespace) -> None:
    """semantics.md §7.3: ``ReadSignalsRequest.min_timestamp`` is a best-effort
    freshness **hint**, not a hard deadline. A provider that cannot satisfy it
    MUST return the best available values (``CODE_OK``) and indicate staleness via
    ``quality``/``Status.details`` — it MUST NOT, by itself, turn an otherwise-
    readable signal into an error (notably ``CODE_DEADLINE_EXCEEDED``). A genuine
    read failure (``CODE_UNAVAILABLE``) is unrelated and exempt; the caller first
    establishes that a hint-free read of the same device succeeds."""
    code = read_response.status.code
    if code in (codes.OK, codes.UNAVAILABLE):
        return
    name = next((n for n, v in vars(codes).items() if v == code), str(code))
    raise ConformanceFailure(
        f"a read with min_timestamp set returned status CODE_{name} — §7.3 freshness is a "
        "best-effort hint that constrains *quality*, not *success*: return best-available "
        "values (CODE_OK) with QUALITY_STALE, not an error such as CODE_DEADLINE_EXCEEDED"
    )


_SNAKE_CASE = re.compile(r"^[a-z][a-z0-9_]*$")


def assert_signal_ids_snake_case(device_id: str, capabilities) -> None:
    """Anolis executable profile — capability convention: every ``signal_id`` is
    snake_case (``^[a-z][a-z0-9_]*$``: lowercase letter first, then lowercase
    letters / digits / underscores; no dots, no camelCase). A *convention*, not
    core ADPP — see ``docs/profiles/anolis-executable-profile-v1.md``; waivable."""
    bad = [s.signal_id for s in capabilities.signals if not _SNAKE_CASE.match(s.signal_id)]
    if bad:
        raise ConformanceFailure(
            f"device {device_id!r}: signal_id(s) must be snake_case "
            f"(^[a-z][a-z0-9_]*$); offending: {bad}"
        )


def assert_function_ids_per_type_from_one(device_id: str, capabilities) -> None:
    """Anolis executable profile — capability convention: a device's
    ``function_id``s are numbered per device type from 1, i.e. the contiguous set
    ``{1..N}`` for N declared functions (not a global counter like 1001+, not an
    arbitrary value like 10). A *convention*, not core ADPP — see
    ``docs/profiles/anolis-executable-profile-v1.md``; waivable."""
    ids = sorted(f.function_id for f in capabilities.functions)
    if ids and ids != list(range(1, len(ids) + 1)):
        raise ConformanceFailure(
            f"device {device_id!r}: function_ids should be per-type {{1..{len(ids)}}}; got {ids}"
        )


def assert_config_schema_envelope(stdout: str) -> None:
    """Anolis executable profile §2: ``--config-schema`` prints a thin, versioned
    envelope wrapping a provider-owned JSON Schema. Asserts *shape* only — a
    parseable JSON **object**; an integer ``config_schema_version`` >= 1; and
    ``schema`` a JSON object (JSON-Schema-shaped). The *content* of ``schema`` is
    provider-owned and deliberately NOT asserted. See
    ``docs/profiles/anolis-executable-profile-v1.md``; waivable."""
    try:
        doc = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ConformanceFailure(
            f"--config-schema must print a JSON object to stdout; got unparseable output ({exc})"
        )
    if not isinstance(doc, dict):
        raise ConformanceFailure(f"--config-schema envelope must be a JSON object; got {type(doc).__name__}")
    ver = doc.get("config_schema_version")
    # bool is an int subclass — reject it explicitly (matches profiles.py's level guard).
    if isinstance(ver, bool) or not isinstance(ver, int) or ver < 1:
        raise ConformanceFailure(f"envelope 'config_schema_version' must be an integer >= 1; got {ver!r}")
    schema = doc.get("schema")
    if not isinstance(schema, dict):
        raise ConformanceFailure(f"envelope 'schema' must be a JSON object (a JSON Schema); got {type(schema).__name__}")


_CHECK_HOST_STATUSES = ("met", "unmet", "unknown")


def assert_check_host_envelope(stdout: str, returncode: int) -> None:
    """Anolis executable profile §3: ``--check-host <config>`` prints a versioned
    envelope listing provider-owned host requirements, and its exit code agrees
    with them. Asserts *shape* and that agreement only — a parseable JSON
    **object**; an integer ``check_host_version`` >= 1; ``requirements`` an array
    of objects, each with a non-empty string ``id`` and a ``status`` of
    met/unmet/unknown; and exit ``1`` exactly when some status is ``unmet``
    (``0`` otherwise). What the requirements *are* is provider-owned and
    deliberately NOT asserted. Exit ``2`` (could not evaluate) is not a valid
    answer for a config the harness knows is valid. See
    ``docs/profiles/anolis-executable-profile-v1.md``; waivable."""
    try:
        doc = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise ConformanceFailure(
            f"--check-host must print a JSON object to stdout; got unparseable output ({exc})"
        )
    if not isinstance(doc, dict):
        raise ConformanceFailure(f"--check-host envelope must be a JSON object; got {type(doc).__name__}")
    ver = doc.get("check_host_version")
    # bool is an int subclass — reject it explicitly (matches the config-schema guard).
    if isinstance(ver, bool) or not isinstance(ver, int) or ver < 1:
        raise ConformanceFailure(f"envelope 'check_host_version' must be an integer >= 1; got {ver!r}")
    reqs = doc.get("requirements")
    if not isinstance(reqs, list):
        raise ConformanceFailure(f"envelope 'requirements' must be an array; got {type(reqs).__name__}")
    unmet = False
    for i, req in enumerate(reqs):
        if not isinstance(req, dict):
            raise ConformanceFailure(f"requirements[{i}] must be a JSON object; got {type(req).__name__}")
        rid = req.get("id")
        if not isinstance(rid, str) or not rid:
            raise ConformanceFailure(f"requirements[{i}].id must be a non-empty string; got {rid!r}")
        status = req.get("status")
        if status not in _CHECK_HOST_STATUSES:
            raise ConformanceFailure(
                f"requirements[{i}] ({rid}).status must be one of {_CHECK_HOST_STATUSES}; got {status!r}"
            )
        unmet = unmet or status == "unmet"
    expected = 1 if unmet else 0
    if returncode != expected:
        raise ConformanceFailure(
            f"--check-host exit code must be {expected} when {'some' if unmet else 'no'} requirement "
            f"is unmet; got {returncode}"
        )


def _defined_error_codes(codes: SimpleNamespace) -> set[int]:
    """Every status code the proto enum defines, minus OK and UNSPECIFIED."""
    return set(vars(codes).values()) - {codes.OK, codes.UNSPECIFIED}


def assert_controlled_malformed(
    client: AdppClient,
    codes: SimpleNamespace,
    *,
    timeout: float = 3.0,
    settle: float = 0.5,
) -> None:
    """A provider's response to a malformed/garbage frame must be *controlled*.

    Accepted:
    - a well-formed framed response carrying a real **error** status, after which
      the process does not crash; or
    - a clean documented exit (codes 0/2/3).

    Rejected (raise :class:`ConformanceFailure`):
    - a hang;
    - a crash (killed by a signal -> negative return code), including
      respond-then-crash;
    - a response with no status, or one carrying ``CODE_OK`` / ``CODE_UNSPECIFIED``
      (garbage must never read as success);
    - an undocumented exit code, or an over-cap/unparseable response
      (``await_outcome`` surfaces these as exceptions to the caller).
    """
    try:
        outcome, value = client.await_outcome(timeout)
    except ProviderHang as exc:
        raise ConformanceFailure(str(exc)) from None

    if outcome == "response":
        if not value.HasField("status"):
            raise ConformanceFailure("malformed input produced a response with no status")
        code = value.status.code
        # Must be a DEFINED error code — not OK, not UNSPECIFIED, and not some
        # arbitrary integer outside the enum.
        if code not in _defined_error_codes(codes):
            raise ConformanceFailure(
                f"malformed input must yield a defined error status; got code={code} "
                f"message={value.status.message!r}"
            )
        # A provider may respond-then-exit, but only with a documented exit code;
        # a crash (negative) or an undocumented exit after responding is a failure.
        rc = client.settle_exit(settle)
        if rc is not None and rc not in spec.ALLOWED_MALFORMED_EXIT_CODES:
            raise ConformanceFailure(
                f"provider emitted a response then exited {rc} "
                f"(allowed: {sorted(spec.ALLOWED_MALFORMED_EXIT_CODES)}; negative = crash)"
            )
        return

    # outcome == "exit"
    if value is None:
        raise ConformanceFailure("provider did not produce an exit code")
    if value < 0:
        raise ConformanceFailure(
            f"provider crashed on malformed input (killed by signal, returncode={value})"
        )
    if value not in spec.ALLOWED_MALFORMED_EXIT_CODES:
        raise ConformanceFailure(
            f"provider exited {value} on malformed input "
            f"(allowed: {sorted(spec.ALLOWED_MALFORMED_EXIT_CODES)})"
        )
