"""ADPP v1 *core protocol* conformance — messages, status, correlation,
capabilities, and read/call semantics. Assertions follow docs/semantics.md (the
normative spec); where the spec permits a choice, the test accepts every
permitted behavior.
"""

from __future__ import annotations

import time

import pytest

from . import spec
from .checks import assert_freshness_hint_not_fatal, assert_get_health, assert_status_present
from .client import AdppClient
from .profiles import SUPPORTED_CONFORMANCE_LEVEL


# ---- handshake / version ------------------------------------------------
def test_hello_v1_ok(client: AdppClient, profile, codes, status_text) -> None:
    resp = client.hello()
    assert_status_present(resp)  # semantics.md §10: every Response carries a Status
    assert resp.status.code == codes.OK, status_text(resp)
    assert resp.request_id == 1, "Hello response must echo request_id"
    assert resp.hello.protocol_version == spec.PROTOCOL_VERSION
    assert resp.hello.provider_name == profile.expected_provider_name


def test_hello_conformance_level_matches_manifest(client: AdppClient, profile) -> None:
    # semantics.md "Conformance levels": when a provider advertises
    # conformance_level in Hello metadata AND declares one in its manifest, the two
    # MUST agree, at every level. Advertising is a SHOULD (absent means 1), so a
    # provider that does not advertise skips.
    advertised = dict(client.hello().hello.metadata).get("conformance_level")
    if advertised is None:
        pytest.skip("provider does not advertise conformance_level (SHOULD, not MUST)")
    try:
        level = int(advertised)
    except ValueError:
        pytest.fail(f"Hello conformance_level metadata {advertised!r} is not an integer")
    assert 1 <= level <= SUPPORTED_CONFORMANCE_LEVEL, (
        f"Hello advertises unsupported conformance_level {level}"
    )
    assert level == profile.conformance_level, (
        f"Hello conformance_level {level} != manifest conformance_level {profile.conformance_level}"
    )


def test_hello_unsupported_version_rejected(client: AdppClient, codes, status_text) -> None:
    # semantics.md 3: an unsupported version MUST be FAILED_PRECONDITION *or*
    # UNIMPLEMENTED (both conformant).
    resp = client.hello(protocol_version="v999")
    assert resp.status.code in (codes.FAILED_PRECONDITION, codes.UNIMPLEMENTED), (
        f"non-v1 Hello must be FAILED_PRECONDITION or UNIMPLEMENTED; got {status_text(resp)}"
    )


def test_request_id_correlation(ready_client: AdppClient) -> None:
    # semantics.md 4: providers MUST echo the request_id of each request.
    first = ready_client.list_devices().request_id
    second = ready_client.list_devices().request_id
    assert second == first + 1, "each response must echo its request's id"


# ---- inventory / capabilities ------------------------------------------
def test_list_devices_ok(ready_client: AdppClient, profile, codes, status_text) -> None:
    resp = ready_client.list_devices()
    assert resp.status.code == codes.OK, status_text(resp)
    if profile.has_mock_devices:
        assert len(resp.list_devices.devices) >= 1, "conformance config should yield >=1 device"


def test_list_devices_include_health(ready_client: AdppClient, profile, codes, status_text) -> None:
    resp = ready_client.list_devices(include_health=True)
    assert resp.status.code == codes.OK, status_text(resp)
    device_ids = {d.device_id for d in resp.list_devices.devices}
    health_ids = {dh.device_id for dh in resp.list_devices.device_health}
    # Health entries must reference real devices.
    unknown = health_ids - device_ids
    assert not unknown, f"device_health references unknown devices {unknown}"
    # inventory.proto: when include_health is true the response "will include
    # per-device health entries". For a profile with mock devices, require it.
    if profile.has_mock_devices and device_ids:
        assert health_ids, "include_health=true must populate per-device health entries"
        missing = device_ids - health_ids
        assert not missing, f"include_health=true must cover every device; missing {missing}"


def test_describe_device(ready_client: AdppClient, codes, status_text) -> None:
    devices = ready_client.list_devices().list_devices.devices
    if not devices:
        pytest.skip("no devices to describe")
    resp = ready_client.describe_device(devices[0].device_id)
    assert resp.status.code == codes.OK, status_text(resp)
    # semantics.md §6.1 requires the COMPLETE CapabilitySet, not a non-empty one —
    # a zero-capability device is valid ADPP. (A provider that expects capabilities
    # on its mock devices can assert that in its own profile/suite.)
    assert resp.describe_device.HasField("capabilities"), "DescribeDevice must return a CapabilitySet"


def test_describe_unknown_device_not_found(ready_client: AdppClient, codes, status_text) -> None:
    resp = ready_client.describe_device("__no_such_device__")
    assert resp.status.code == codes.NOT_FOUND, (
        f"unknown device must be CODE_NOT_FOUND; got {status_text(resp)}"
    )


# ---- read / call --------------------------------------------------------
def test_read_signals_response_shape(ready_client: AdppClient, codes, status_text) -> None:
    devices = ready_client.list_devices().list_devices.devices
    if not devices:
        pytest.skip("no devices to read")
    resp = ready_client.read_signals(devices[0].device_id)  # default signal set
    # A default read must succeed, or the mock backend may legitimately report
    # CODE_UNAVAILABLE — but never an arbitrary error (INTERNAL/INVALID_ARGUMENT/…).
    assert resp.status.code in (codes.OK, codes.UNAVAILABLE), (
        f"default read must be OK or UNAVAILABLE; got {status_text(resp)}"
    )
    if resp.status.code == codes.OK:
        for value in resp.read_signals.values:
            assert value.signal_id, "each SignalValue must carry a signal_id"
            assert value.HasField("value"), f"signal {value.signal_id} missing a value"


def test_default_read_returns_declared_subset(ready_client: AdppClient, codes, status_text) -> None:
    # semantics.md §7.2: for a device type declaring >=1 signal, an empty-`signal_ids`
    # read returns the DEFAULT signal set — a non-empty subset of the declared
    # signals. The set is provider-curated, so this asserts "non-empty ⊆ declared",
    # NOT an exact membership. (This is T0.2: a provider that returns nothing on a
    # default read fails §7.2.)
    checked = 0
    for d in ready_client.list_devices().list_devices.devices:
        caps = ready_client.describe_device(d.device_id).describe_device.capabilities
        declared = {s.signal_id for s in caps.signals}
        if not declared:
            continue
        resp = ready_client.read_signals(d.device_id)  # empty signal_ids => default set
        # A mock backend may legitimately report UNAVAILABLE; the set contract is
        # only observable on an OK read.
        if resp.status.code == codes.UNAVAILABLE:
            continue
        assert resp.status.code == codes.OK, (
            f"default read must be OK or UNAVAILABLE; got {status_text(resp)}"
        )
        default_ids = {v.signal_id for v in resp.read_signals.values}
        assert default_ids, (
            f"device {d.device_id} declares signals but a default read returned none "
            "(§7.2 requires a non-empty default signal set)"
        )
        assert default_ids <= declared, (
            f"default read returned undeclared signals {default_ids - declared}"
        )
        checked += 1
    if checked == 0:
        pytest.skip("no readable device declares signals")


def test_min_timestamp_hint_is_not_fatal(ready_client: AdppClient, codes, status_text) -> None:
    # semantics.md §7.3: `ReadSignalsRequest.min_timestamp` is a best-effort
    # freshness HINT. A provider that cannot satisfy it MUST return best-available
    # values (CODE_OK) — indicating staleness via quality/Status.details — and MUST
    # NOT turn an otherwise-readable signal into an error (notably
    # CODE_DEADLINE_EXCEEDED). We use a min_timestamp an hour in the future, which
    # no real reading can satisfy, so the hint is always unmet.
    future = (int(time.time()) + 3600, 0)
    checked = 0
    for d in ready_client.list_devices().list_devices.devices:
        caps = ready_client.describe_device(d.device_id).describe_device.capabilities
        if not caps.signals:
            continue
        # Establish that the device is readable at all without the hint; a mock
        # backend may report UNAVAILABLE, in which case the contract is unobservable.
        base = ready_client.read_signals(d.device_id)
        if base.status.code == codes.UNAVAILABLE:
            continue
        assert base.status.code == codes.OK, (
            f"baseline (hint-free) read must be OK or UNAVAILABLE; got {status_text(base)}"
        )
        resp = ready_client.read_signals(d.device_id, min_timestamp=future)
        # The unmet freshness hint must not, by itself, fail the read.
        assert_freshness_hint_not_fatal(resp, codes)
        checked += 1
    if checked == 0:
        pytest.skip("no readable device declares signals")


def test_read_unknown_signal_consistent(ready_client: AdppClient, codes, status_text) -> None:
    # semantics.md 7.4: a provider MUST choose ONE consistent behavior for an
    # unknown signal id — either fail CODE_NOT_FOUND, OR return partial results
    # that omit the unknown id. Both are conformant; inconsistency is not.
    devices = ready_client.list_devices().list_devices.devices
    if not devices:
        pytest.skip("no devices")
    dev = devices[0].device_id
    caps = ready_client.describe_device(dev).describe_device.capabilities
    if not caps.signals:
        pytest.skip("device declares no signals")
    known = caps.signals[0].signal_id
    unknown = "__no_such_signal__"

    def policy(signal_ids) -> str:
        resp = ready_client.read_signals(dev, signal_ids)
        if resp.status.code == codes.NOT_FOUND:
            return "fail"
        if resp.status.code == codes.OK:
            returned = {v.signal_id for v in resp.read_signals.values}
            # The response carries values for the REQUESTED signals (minus unknown),
            # never arbitrary/unrelated inventory.
            assert returned <= set(signal_ids), (
                f"partial result returned unrequested signals {returned - set(signal_ids)}"
            )
            assert unknown not in returned, "partial variant must omit the unknown signal id"
            if known in signal_ids:
                assert known in returned, (
                    "partial variant must still return the known signal, not silently drop it"
                )
            return "partial"
        return pytest.fail(  # type: ignore[return-value]
            f"unknown-signal read must be NOT_FOUND or OK(partial); got {status_text(resp)}"
        )

    chosen = policy([known, unknown])
    # The same policy must hold on repeat and for an unknown-only request.
    assert policy([known, unknown]) == chosen, "policy must be stable across identical requests"
    assert policy([unknown]) == chosen, "policy must match for an unknown-only request"


def test_call_unknown_function_by_id_rejected(ready_client: AdppClient, codes, status_text) -> None:
    devices = ready_client.list_devices().list_devices.devices
    if not devices:
        pytest.skip("no devices")
    # semantics.md 8.3: unknown identifiers MUST be CODE_NOT_FOUND.
    resp = ready_client.call(devices[0].device_id, function_id=999999)
    assert resp.status.code == codes.NOT_FOUND, (
        f"unknown function_id must be NOT_FOUND; got {status_text(resp)}"
    )


def test_call_unknown_function_by_name_rejected(ready_client: AdppClient, codes, status_text) -> None:
    devices = ready_client.list_devices().list_devices.devices
    if not devices:
        pytest.skip("no devices")
    # semantics.md 8.3: unknown identifiers (incl. names) MUST be CODE_NOT_FOUND.
    resp = ready_client.call(devices[0].device_id, function_name="__no_such_function__")
    assert resp.status.code == codes.NOT_FOUND, (
        f"unknown function_name must be NOT_FOUND; got {status_text(resp)}"
    )


def test_call_on_unknown_device_rejected(ready_client: AdppClient, codes, status_text) -> None:
    resp = ready_client.call("__no_such_device__", function_id=1)
    assert resp.status.code == codes.NOT_FOUND, (
        f"call on unknown device must be NOT_FOUND; got {status_text(resp)}"
    )


# ---- positive call coverage (L1, spec-backed) --------------------------
def _first_device_with_functions(ready_client: AdppClient):
    """(device_id, [FunctionSpec]) for the first device declaring functions; else (None, [])."""
    for d in ready_client.list_devices().list_devices.devices:
        caps = ready_client.describe_device(d.device_id).describe_device.capabilities
        if caps.functions:
            return d.device_id, list(caps.functions)
    return None, []


def _devices_with_result_functions(ready_client: AdppClient):
    """Yield (device_id, FunctionSpec) for every no-required-arg function that
    declares results. No-required-arg so the call can be made safely."""
    for d in ready_client.list_devices().list_devices.devices:
        caps = ready_client.describe_device(d.device_id).describe_device.capabilities
        for fn in caps.functions:
            if fn.results and not any(a.required for a in fn.args):
                yield d.device_id, fn


def test_call_declared_results_are_populated(ready_client: AdppClient, codes, status_text) -> None:
    # semantics.md §8.1 + call.proto: CallResponse.results is a map keyed by
    # ArgSpec.name from FunctionSpec.results. A SYNCHRONOUS successful call to a
    # function that DECLARES results MUST populate them — this is T0.6: declare
    # *and* populate, not declare-then-return-empty. An async-accepted call
    # (CODE_OK with operation_id set, §8.1) observes results later via signals and
    # is exempt. We try every candidate function and assert on the first that
    # reaches a synchronous OK (a mock backend may report UNAVAILABLE for some).
    candidates = list(_devices_with_result_functions(ready_client))
    if not candidates:
        pytest.skip("no zero-required-arg function declares results")
    for dev, fn in candidates:
        resp = ready_client.call(dev, function_id=fn.function_id)
        if resp.status.code == codes.UNAVAILABLE:
            continue  # mock backend cannot actuate this one; try the next
        assert resp.status.code == codes.OK, (
            f"valid call to {fn.name} must be accepted; got {status_text(resp)}"
        )
        if resp.call.operation_id:
            continue  # accepted asynchronously; results observed via signals (§8.1)
        declared = {a.name for a in fn.results}
        returned = set(resp.call.results.keys())
        assert returned, (
            f"function {fn.name} declares results {sorted(declared)} but CallResponse.results "
            "is empty (§8.1: a synchronous successful call must populate declared results)"
        )
        assert returned <= declared, (
            f"CallResponse.results contains undeclared keys {returned - declared}"
        )
        return
    pytest.skip("no result-declaring function reached a synchronous OK call")


def test_call_valid_no_arg_function_accepted(ready_client: AdppClient, codes, status_text) -> None:
    # A well-formed call to a function with no required args must be ACCEPTED:
    # CODE_OK, or CODE_UNAVAILABLE if the mock backend cannot actuate. It must not
    # be rejected as INVALID_ARGUMENT/NOT_FOUND/OUT_OF_RANGE — the function exists
    # and nothing required is missing. Exercises the positive call path by id+name.
    dev, fns = _first_device_with_functions(ready_client)
    if not fns:
        pytest.skip("no device declares functions")
    no_req = [f for f in fns if not any(a.required for a in f.args)]
    if not no_req:
        pytest.skip("no zero-required-argument function to call safely")
    fn = no_req[0]
    accepted = (codes.OK, codes.UNAVAILABLE)
    by_id = ready_client.call(dev, function_id=fn.function_id)
    assert by_id.status.code in accepted, f"valid call by function_id must be accepted; got {status_text(by_id)}"
    by_name = ready_client.call(dev, function_name=fn.name)
    assert by_name.status.code in accepted, f"valid call by function_name must be accepted; got {status_text(by_name)}"


def test_call_missing_required_arg_is_invalid(ready_client: AdppClient, codes, status_text) -> None:
    # semantics.md 8.3: omitting a required argument is CODE_INVALID_ARGUMENT.
    dev, fns = _first_device_with_functions(ready_client)
    if not fns:
        pytest.skip("no device declares functions")
    with_req = [f for f in fns if any(a.required for a in f.args)]
    if not with_req:
        pytest.skip("no function declares a required argument")
    fn = with_req[0]
    resp = ready_client.call(dev, function_id=fn.function_id)  # omit all args
    assert resp.status.code == codes.INVALID_ARGUMENT, (
        f"call omitting a required arg must be INVALID_ARGUMENT; got {status_text(resp)}"
    )


def test_call_function_id_preferred_over_name(ready_client: AdppClient, codes, status_text) -> None:
    # semantics.md 6.2: when function_id is set, function_name is ignored. The
    # outcome must not change when an (ignored) function_name is added.
    dev, fns = _first_device_with_functions(ready_client)
    if not fns:
        pytest.skip("no device declares functions")
    fn = fns[0]
    only_id = ready_client.call(dev, function_id=fn.function_id)
    with_name = ready_client.call(dev, function_id=fn.function_id, function_name="__ignored_name__")
    assert only_id.status.code == with_name.status.code, (
        "function_name must be ignored when function_id is set (6.2); "
        f"got {status_text(only_id)} vs {status_text(with_name)}"
    )


# ---- health -------------------------------------------------------------
def test_get_health_well_formed(ready_client: AdppClient, codes) -> None:
    # semantics.md §9.1: GetHealth MUST return ProviderHealth (L1). The runtime
    # calls it for its health snapshot (anolis core/health/health_snapshot.cpp).
    listed = {d.device_id for d in ready_client.list_devices().list_devices.devices}
    assert_get_health(ready_client.get_health(), codes, listed)
