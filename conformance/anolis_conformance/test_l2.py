"""ADPP conformance **level 2** ([L2]) tests.

The strengthened bar from `semantics.md`: pre-Hello handling (§3.2), bounds →
`OUT_OF_RANGE` + non-finite → `INVALID_ARGUMENT` (§8.3), deadlines (§8.4) and value
timestamp/quality (§7.1). Hello/manifest level agreement applies at every level,
so it lives in test_adpp_core.py. The whole module is
marked `conformance_level(2)`, so the harness collects it only when the provider's
manifest declares `conformance_level >= 2`. An L1 provider never runs these.

Not covered generically (documented as manual coverage in ADPP-CONFORMANCE.md):
a deadline expiring *during* synchronous execution, and proving no side effects —
both need a deterministic slow/observable mock function.
"""

from __future__ import annotations

import math
import time

import pytest

from .checks import assert_signalvalues_l2
from .client import AdppClient

pytestmark = pytest.mark.conformance_level(2)

_INT64_MIN, _INT64_MAX = -(2**63), 2**63 - 1
_UINT64_MAX = 2**64 - 1


# ---- discovery + value/argument synthesis ------------------------------
def _devices_with_caps(client: AdppClient):
    for d in client.list_devices().list_devices.devices:
        caps = client.describe_device(d.device_id).describe_device.capabilities
        yield d.device_id, caps


def _first_device_with_functions(client: AdppClient):
    for dev, caps in _devices_with_caps(client):
        if caps.functions:
            return dev, list(caps.functions)
    return None, []


def _numeric_types(protocol):
    return (protocol.VALUE_TYPE_DOUBLE, protocol.VALUE_TYPE_INT64, protocol.VALUE_TYPE_UINT64)


def _make_value(protocol, vtype, number):
    v = protocol.Value()
    v.type = vtype
    if vtype == protocol.VALUE_TYPE_DOUBLE:
        v.double_value = float(number)
    elif vtype == protocol.VALUE_TYPE_INT64:
        v.int64_value = int(number)
    elif vtype == protocol.VALUE_TYPE_UINT64:
        v.uint64_value = int(number)
    return v


def _bound(arg, vtype, which, protocol):
    """The declared min/max bound for a numeric arg, or None if absent."""
    field = {
        protocol.VALUE_TYPE_DOUBLE: f"{which}_double",
        protocol.VALUE_TYPE_INT64: f"{which}_int64",
        protocol.VALUE_TYPE_UINT64: f"{which}_uint64",
    }[vtype]
    return getattr(arg, field) if arg.HasField(field) else None


def _just_above(vtype, bound, protocol):
    if vtype == protocol.VALUE_TYPE_DOUBLE:
        nxt = math.nextafter(bound, math.inf)
        return nxt if nxt != bound else None
    if vtype == protocol.VALUE_TYPE_INT64:
        return bound + 1 if bound < _INT64_MAX else None
    return bound + 1 if bound < _UINT64_MAX else None


def _just_below(vtype, bound, protocol):
    if vtype == protocol.VALUE_TYPE_DOUBLE:
        nxt = math.nextafter(bound, -math.inf)
        return nxt if nxt != bound else None
    if vtype == protocol.VALUE_TYPE_INT64:
        return bound - 1 if bound > _INT64_MIN else None
    return bound - 1 if bound > 0 else None


def _synth_value(protocol, arg):
    """A valid in-bounds Value for an ArgSpec, or None if not synthesizable."""
    v = protocol.Value()
    v.type = arg.type
    if arg.type == protocol.VALUE_TYPE_BOOL:
        v.bool_value = False
    elif arg.type == protocol.VALUE_TYPE_INT64:
        v.int64_value = arg.min_int64 if arg.HasField("min_int64") else 0
    elif arg.type == protocol.VALUE_TYPE_UINT64:
        v.uint64_value = arg.min_uint64 if arg.HasField("min_uint64") else 0
    elif arg.type == protocol.VALUE_TYPE_DOUBLE:
        if arg.HasField("min_double"):
            v.double_value = arg.min_double
        elif arg.HasField("max_double"):
            v.double_value = arg.max_double
        else:
            v.double_value = 0.0
    elif arg.type == protocol.VALUE_TYPE_STRING:
        v.string_value = arg.allowed_values[0] if arg.allowed_values else ""
    elif arg.type == protocol.VALUE_TYPE_BYTES:
        v.bytes_value = b""
    else:
        return None
    return v


def _synth_required_args(protocol, fn):
    out = {}
    for a in fn.args:
        if not a.required:
            continue
        value = _synth_value(protocol, a)
        if value is None:
            return None
        out[a.name] = value
    return out


def _wait(seconds: float) -> None:
    if seconds > 0:
        time.sleep(min(seconds, 2.0))  # cap to keep CI bounded


# ---- §3.2 pre-Hello (every non-Hello request kind) ---------------------
@pytest.mark.parametrize(
    "send",
    ["list_devices", "describe_device", "read_signals", "call", "wait_ready", "get_health"],
)
def test_l2_request_before_hello_rejected(
    client: AdppClient, codes, status_text, send
) -> None:
    # A non-Hello request before a successful Hello → FAILED_PRECONDITION, not processed.
    dispatch = {
        "list_devices": lambda: client.list_devices(),
        "describe_device": lambda: client.describe_device("x"),
        "read_signals": lambda: client.read_signals("x"),
        "call": lambda: client.call("x", function_id=1),
        "wait_ready": lambda: client.wait_ready(),
        "get_health": lambda: client.get_health(),
    }
    resp = dispatch[send]()  # deliberately no Hello first
    assert resp.status.code == codes.FAILED_PRECONDITION, (
        f"{send} before Hello must be CODE_FAILED_PRECONDITION; got {status_text(resp)}"
    )


# ---- §7.1 value timestamp + quality (all devices, default + explicit) --
def test_l2_ok_signalvalues_have_timestamp_and_quality(
    ready_client: AdppClient, codes, status_text
) -> None:
    exercised = 0
    for dev, caps in _devices_with_caps(ready_client):
        default = ready_client.read_signals(dev)
        if default.status.code == codes.OK:
            assert_signalvalues_l2(default)
            exercised += 1
        signal_ids = [s.signal_id for s in caps.signals]
        if signal_ids:
            explicit = ready_client.read_signals(dev, signal_ids)
            if explicit.status.code == codes.OK:  # includes the partial-success form
                assert_signalvalues_l2(explicit)
                exercised += 1
    if exercised == 0:
        pytest.skip("no device produced an OK read to validate")


# ---- §8.3 bounds → OUT_OF_RANGE (all numeric types, inclusive) ---------
def test_l2_numeric_bounds_enforced(
    ready_client: AdppClient, codes, status_text, protocol
) -> None:
    numeric = _numeric_types(protocol)
    exercised = 0
    for dev, caps in _devices_with_caps(ready_client):
        for fn in caps.functions:
            base = _synth_required_args(protocol, fn)
            if base is None:
                continue
            # Sanity: with all required args valid the call must be accepted (OK,
            # not UNAVAILABLE) so a later out-of-bounds result isolates the bound.
            if ready_client.call(dev, function_id=fn.function_id, args=base).status.code != codes.OK:
                continue
            interval = fn.policy.min_interval_ms / 1000.0
            for arg in fn.args:
                if arg.type not in numeric:
                    continue
                for which, past_of in (("min", _just_below), ("max", _just_above)):
                    bound = _bound(arg, arg.type, which, protocol)
                    if bound is None:
                        continue
                    # Inclusive: the value AT the bound is valid.
                    _wait(interval)
                    at = dict(base)
                    at[arg.name] = _make_value(protocol, arg.type, bound)
                    r = ready_client.call(dev, function_id=fn.function_id, args=at)
                    assert r.status.code == codes.OK, (
                        f"{fn.name}/{arg.name}: value AT the {which} bound ({bound}) is valid; "
                        f"got {status_text(r)}"
                    )
                    past = past_of(arg.type, bound, protocol)
                    if past is None:
                        continue  # no representable value beyond this bound
                    _wait(interval)
                    oob = dict(base)
                    oob[arg.name] = _make_value(protocol, arg.type, past)
                    r2 = ready_client.call(dev, function_id=fn.function_id, args=oob)
                    assert r2.status.code == codes.OUT_OF_RANGE, (
                        f"{fn.name}/{arg.name}: value {past} past the {which} bound ({bound}) "
                        f"must be CODE_OUT_OF_RANGE; got {status_text(r2)}"
                    )
                    exercised += 1
    if exercised == 0:
        pytest.skip("no isolatable bounded numeric argument to exercise")


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")], ids=["nan", "inf", "-inf"])
def test_l2_non_finite_double_is_invalid_argument(
    ready_client: AdppClient, codes, status_text, protocol, bad
) -> None:
    for dev, caps in _devices_with_caps(ready_client):
        for fn in caps.functions:
            arg = next(
                (
                    a
                    for a in fn.args
                    if a.type == protocol.VALUE_TYPE_DOUBLE
                    and (a.HasField("min_double") or a.HasField("max_double"))
                ),
                None,
            )
            if arg is None:
                continue
            base = _synth_required_args(protocol, fn)
            if base is None:
                continue
            if ready_client.call(dev, function_id=fn.function_id, args=base).status.code != codes.OK:
                continue
            _wait(fn.policy.min_interval_ms / 1000.0)
            args = dict(base)
            args[arg.name] = _make_value(protocol, protocol.VALUE_TYPE_DOUBLE, bad)
            resp = ready_client.call(dev, function_id=fn.function_id, args=args)
            assert resp.status.code == codes.INVALID_ARGUMENT, (
                f"{fn.name}/{arg.name}: non-finite double must be CODE_INVALID_ARGUMENT; "
                f"got {status_text(resp)}"
            )
            return
    pytest.skip("no isolatable bounded-double function to exercise")


# ---- §8.4 deadlines ----------------------------------------------------
def test_l2_deadline_metadata_well_formed(client: AdppClient) -> None:
    value = dict(client.hello().hello.metadata).get("supports_deadlines")
    if value is not None:
        assert value in ("true", "false"), (
            f"supports_deadlines metadata must be 'true' or 'false'; got {value!r}"
        )


def _ready_for_calls(client: AdppClient):
    """Hello (+WaitReady) and return (metadata, device_id, [FunctionSpec])."""
    meta = dict(client.hello().hello.metadata)
    if meta.get("supports_wait_ready") == "true":
        client.wait_ready()
    dev, fns = _first_device_with_functions(client)
    return meta, dev, fns


def test_l2_expired_deadline_exceeded(
    client: AdppClient, codes, status_text, protocol
) -> None:
    meta, dev, fns = _ready_for_calls(client)
    if meta.get("supports_deadlines") != "true":
        pytest.skip("provider does not advertise supports_deadlines")
    if not fns:
        pytest.skip("no functions to call")
    base = _synth_required_args(protocol, fns[0])
    if base is None:
        pytest.skip("cannot synthesize valid arguments")
    past = (int(time.time()) - 3600, 0)  # an hour ago — already expired
    resp = client.call(dev, function_id=fns[0].function_id, args=base, deadline=past)
    assert resp.status.code == codes.DEADLINE_EXCEEDED, (
        f"an already-expired deadline must yield CODE_DEADLINE_EXCEEDED; got {status_text(resp)}"
    )


def test_l2_malformed_deadline_is_invalid_argument(
    client: AdppClient, codes, status_text, protocol
) -> None:
    meta, dev, fns = _ready_for_calls(client)
    if meta.get("supports_deadlines") != "true":
        pytest.skip("provider does not advertise supports_deadlines")
    if not fns:
        pytest.skip("no functions to call")
    base = _synth_required_args(protocol, fns[0])
    if base is None:
        pytest.skip("cannot synthesize valid arguments")
    malformed = (int(time.time()), 2_000_000_000)  # nanos out of [0, 1e9)
    resp = client.call(dev, function_id=fns[0].function_id, args=base, deadline=malformed)
    assert resp.status.code == codes.INVALID_ARGUMENT, (
        f"a malformed deadline (nanos out of range) must yield CODE_INVALID_ARGUMENT; "
        f"got {status_text(resp)}"
    )
