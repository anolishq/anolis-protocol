"""Verifier self-tests: drive the harness against deliberately-faulty fake
providers and prove it REJECTS them. Hermetic — no external binary, no provider
options required. This is what makes the harness trustworthy as a verifier.
"""

from __future__ import annotations

import os
import stat
import struct
import sys
import time

import pytest

from .checks import (
    ConformanceFailure,
    assert_check_host_envelope,
    assert_config_schema_envelope,
    assert_controlled_malformed,
    assert_freshness_hint_not_fatal,
    assert_function_ids_per_type_from_one,
    assert_signal_ids_snake_case,
    assert_signalvalues_l2,
    assert_status_present,
)
from .client import (
    AdppClient,
    CorrelationError,
    OversizedResponse,
    ProviderClosed,
    ProviderHang,
)
from .profiles import load_profile

# A single fake provider; FAKE_MODE selects the misbehavior. It reads one request
# frame, then acts. Response-building modes import the installed protobufs. The
# shebang is filled in with the test interpreter (which has protobuf available).
_FAKE_SRC = r'''import os, sys, struct, time
mode = os.environ.get("FAKE_MODE", "good")
def read_exact(n):
    b = b""
    while len(b) < n:
        c = sys.stdin.buffer.read(n - len(b))
        if not c:
            sys.exit(0)
        b += c
    return b
body = read_exact(struct.unpack("<I", read_exact(4))[0])
out = sys.stdout.buffer
if mode == "hang":
    time.sleep(60)
elif mode == "crash_signal":
    os.abort()                                   # SIGABRT -> negative returncode
elif mode == "exit_bad":
    sys.exit(7)                                  # undocumented exit code
elif mode == "oversized":
    out.write(struct.pack("<I", 1 << 30)); out.flush(); time.sleep(10)
elif mode == "drip":
    out.write(struct.pack("<I", 100)); out.flush()
    for _ in range(100):
        out.write(b"x"); out.flush(); time.sleep(0.5)
elif mode == "mid_frame":
    out.write(struct.pack("<I", 100)); out.write(b"abc"); out.flush(); sys.exit(0)
elif mode in ("respond_ok", "respond_unspecified", "respond_error",
              "respond_then_crash", "respond_error_then_exit_bad"):
    # Reply to a (malformed) frame without parsing it, to test the malformed-input
    # validator: success/unspecified statuses, respond-then-crash, and
    # respond-then-undocumented-exit must all be rejected.
    import protocol_pb2 as p
    resp = p.Response(); resp.request_id = 1
    if mode == "respond_ok":
        resp.status.code = p.Status.Code.Value("CODE_OK")
    elif mode == "respond_unspecified":
        resp.status.message = "unspecified"          # marks status present; code stays 0
    else:
        resp.status.code = p.Status.Code.Value("CODE_NOT_FOUND"); resp.status.message = "nope"
    data = resp.SerializeToString()
    out.write(struct.pack("<I", len(data)) + data); out.flush()
    if mode == "respond_then_crash":
        os.abort()                                   # SIGABRT -> negative exit
    if mode == "respond_error_then_exit_bad":
        sys.exit(7)                                  # undocumented exit after a response
    time.sleep(60)
else:
    import protocol_pb2 as p
    req = p.Request(); req.ParseFromString(body)
    resp = p.Response()
    resp.request_id = req.request_id + (1000 if mode == "wrong_id" else 0)
    if mode != "no_status":
        resp.status.code = p.Status.Code.Value("CODE_OK")
    resp.hello.protocol_version = "v1"; resp.hello.provider_name = "fake"
    data = resp.SerializeToString()
    out.write(struct.pack("<I", len(data)) + data); out.flush()
    time.sleep(60)
'''


@pytest.fixture(scope="session")
def fake_provider(tmp_path_factory) -> str:
    path = tmp_path_factory.mktemp("fake") / "fake_provider.py"
    # Run the fake with the SAME interpreter as the tests (it has protobuf).
    path.write_text(f"#!{sys.executable}\n{_FAKE_SRC}")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    return str(path)


@pytest.fixture
def make_client(protocol, fake_provider, tmp_path, monkeypatch):
    cfg = tmp_path / "dummy.yaml"
    cfg.write_text("{}\n")

    def _make(mode: str) -> AdppClient:
        monkeypatch.setenv("FAKE_MODE", mode)
        return AdppClient(protocol, fake_provider, cfg)

    return _make


def _send_hello(client: AdppClient) -> None:
    req = client.protocol.Request(request_id=1)
    req.hello.protocol_version = "v1"
    req.hello.client_name = "selftest"
    req.hello.client_version = "0.1"
    client.send_frame(req.SerializeToString())


def test_selftest_good_provider_accepted(make_client) -> None:
    client = make_client("good")
    try:
        assert client.hello().status.code != 0  # CODE_OK == 1; sanity that it round-trips
    finally:
        client.close()


def test_selftest_hang_detected(make_client) -> None:
    client = make_client("hang")
    try:
        _send_hello(client)
        with pytest.raises(ProviderHang):
            client.await_outcome(timeout=1.0)
    finally:
        client.close()


def test_selftest_crash_signal_detected(make_client) -> None:
    client = make_client("crash_signal")
    try:
        _send_hello(client)
        outcome, code = client.await_outcome(timeout=3.0)
        assert outcome == "exit" and code is not None and code < 0, (
            f"a signal-killed provider must surface a negative exit code; got {outcome},{code}"
        )
    finally:
        client.close()


def test_selftest_oversized_response_rejected(make_client) -> None:
    client = make_client("oversized")
    try:
        _send_hello(client)
        with pytest.raises(OversizedResponse):
            client.read_response(timeout=3.0)
    finally:
        client.close()


def test_selftest_drip_respects_deadline(make_client) -> None:
    client = make_client("drip")
    try:
        _send_hello(client)
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            client.read_response(timeout=1.0)
        assert time.monotonic() - start < 3.0, "a byte-drip must not stretch the deadline"
    finally:
        client.close()


def test_selftest_mid_frame_close_detected(make_client) -> None:
    client = make_client("mid_frame")
    try:
        _send_hello(client)
        with pytest.raises(ProviderClosed):
            client.read_response(timeout=3.0)
    finally:
        client.close()


def test_selftest_wrong_request_id_detected(make_client) -> None:
    client = make_client("wrong_id")
    try:
        with pytest.raises(CorrelationError):
            client.hello()
    finally:
        client.close()


def test_selftest_missing_status_detected(make_client) -> None:
    # Drive the REAL validator the suite uses, and require it to reject a
    # response with no Status (semantics.md §10).
    client = make_client("no_status")
    try:
        resp = client.hello()
        with pytest.raises(ConformanceFailure):
            assert_status_present(resp)
    finally:
        client.close()


# --- malformed-input validator (the REAL check the framed-stdio suite runs) ---


@pytest.mark.parametrize(
    "mode",
    [
        "respond_ok",
        "respond_unspecified",
        "respond_then_crash",
        "respond_error_then_exit_bad",
        "crash_signal",
        "exit_bad",
    ],
)
def test_selftest_malformed_validator_rejects(make_client, codes, mode) -> None:
    client = make_client(mode)
    try:
        client.send_frame(b"\xde\xad not a valid request \x00\x01")
        with pytest.raises(ConformanceFailure):
            assert_controlled_malformed(client, codes, timeout=3.0)
    finally:
        client.close()


def test_selftest_malformed_validator_accepts_error_status(make_client, codes) -> None:
    # The conformant shape: a framed ERROR response, process stays alive.
    client = make_client("respond_error")
    try:
        client.send_frame(b"\xde\xad not a valid request \x00\x01")
        assert_controlled_malformed(client, codes, timeout=3.0)  # must NOT raise
    finally:
        client.close()


# --- L2 SignalValue check (the real §7.1 validator the L2 suite runs) ---


def _good_signal(protocol):
    resp = protocol.Response()
    sv = resp.read_signals.values.add()
    sv.signal_id = "temp"
    sv.timestamp.seconds = 1
    sv.quality = protocol.SignalValue.QUALITY_OK
    return resp, sv


def test_selftest_signalvalues_l2_validator(protocol) -> None:
    # missing timestamp -> rejected
    resp = protocol.Response()
    sv = resp.read_signals.values.add()
    sv.signal_id = "temp"
    with pytest.raises(ConformanceFailure):
        assert_signalvalues_l2(resp)
    sv.timestamp.seconds = 1  # present, but quality still UNSPECIFIED
    with pytest.raises(ConformanceFailure):
        assert_signalvalues_l2(resp)
    # a good value passes
    good, _ = _good_signal(protocol)
    assert_signalvalues_l2(good)


def test_selftest_signalvalues_l2_rejects_bad_quality(protocol) -> None:
    resp, sv = _good_signal(protocol)
    sv.quality = 999  # not a defined Quality enum value
    with pytest.raises(ConformanceFailure):
        assert_signalvalues_l2(resp)


@pytest.mark.parametrize("nanos,seconds", [(1_000_000_000, 1), (-1, 1), (0, 99_999_999_999_999)])
def test_selftest_signalvalues_l2_rejects_bad_timestamp(protocol, nanos, seconds) -> None:
    resp, sv = _good_signal(protocol)
    sv.timestamp.nanos = nanos
    sv.timestamp.seconds = seconds
    with pytest.raises(ConformanceFailure):
        assert_signalvalues_l2(resp)


# --- freshness-hint validator (the real §7.3 check the core suite runs) ---


def test_selftest_freshness_hint_validator(protocol, codes) -> None:
    # §7.3: an unmet min_timestamp hint must not be fatal. OK / UNAVAILABLE pass;
    # any error code (notably DEADLINE_EXCEEDED) is rejected.
    for accepted in ("CODE_OK", "CODE_UNAVAILABLE"):
        resp = protocol.Response()
        resp.status.code = protocol.Status.Code.Value(accepted)
        assert_freshness_hint_not_fatal(resp, codes)  # must NOT raise
    for rejected in ("CODE_DEADLINE_EXCEEDED", "CODE_INTERNAL", "CODE_FAILED_PRECONDITION"):
        resp = protocol.Response()
        resp.status.code = protocol.Status.Code.Value(rejected)
        with pytest.raises(ConformanceFailure):
            assert_freshness_hint_not_fatal(resp, codes)


# --- capability-convention validators (executable profile §6) ---


def _caps(protocol, *, signal_ids=(), function_ids=()):
    caps = protocol.CapabilitySet()
    for sid in signal_ids:
        caps.signals.add().signal_id = sid
    for fid in function_ids:
        caps.functions.add().function_id = fid
    return caps


def test_selftest_signal_id_snake_case_validator(protocol) -> None:
    # snake_case passes; empty set passes vacuously
    assert_signal_ids_snake_case("d", _caps(protocol, signal_ids=["water_temp", "ph_value", "ch1"]))
    assert_signal_ids_snake_case("d", _caps(protocol))
    for bad in ("ph.value", "CamelCase", "Has_Upper", "1leading", "trailing-"):
        with pytest.raises(ConformanceFailure):
            assert_signal_ids_snake_case("d", _caps(protocol, signal_ids=[bad]))


def test_selftest_function_id_per_type_validator(protocol) -> None:
    # contiguous {1..N} passes (any order); empty set passes vacuously
    assert_function_ids_per_type_from_one("d", _caps(protocol, function_ids=[1, 2, 3]))
    assert_function_ids_per_type_from_one("d", _caps(protocol, function_ids=[3, 1, 2]))
    assert_function_ids_per_type_from_one("d", _caps(protocol))
    for bad in ([10], [1001, 1002, 1003], [0, 1], [1, 3], [2, 3]):
        with pytest.raises(ConformanceFailure):
            assert_function_ids_per_type_from_one("d", _caps(protocol, function_ids=bad))


# --- provider-profile loader (the generic schema; ships no implementer data) ---


def test_selftest_profile_loader_accepts_valid(tmp_path) -> None:
    f = tmp_path / "conformance.toml"
    f.write_text(
        'provider_name = "anolis-provider-example"\n'
        "has_mock_devices = false\n"
        "conformance_level = 2\n"
        "[waivers]\n"
        'test_cli_version_flag = "no --version (example/repo#1)"\n'
    )
    load_profile.cache_clear()
    p = load_profile(f)
    assert p.expected_provider_name == "anolis-provider-example"
    assert p.has_mock_devices is False
    assert p.conformance_level == 2
    assert p.xfail_reason("test_cli_version_flag") == "no --version (example/repo#1)"
    assert p.xfail_reason("test_unwaived") is None


def test_selftest_profile_loader_defaults(tmp_path) -> None:
    f = tmp_path / "minimal.toml"
    f.write_text('provider_name = "x"\n')
    load_profile.cache_clear()
    p = load_profile(f)
    assert p.has_mock_devices is True and p.known_xfails == {}
    assert p.conformance_level == 1  # default


@pytest.mark.parametrize(
    "body",
    [
        'has_mock_devices = true\n',  # missing provider_name
        "provider_name = 42\n",  # non-string provider_name
        'provider_name = "x"\nhas_mock_devices = "yes"\n',  # non-bool flag
        'provider_name = "x"\n[waivers]\nt = 5\n',  # non-string waiver reason
        'provider_name = "x"\nnot valid toml\n',  # malformed TOML
        'provider_name = "x"\nhas_mock_device = true\n',  # unknown key (typo)
        'provider_name = "x"\nconformance_level = 0\n',  # level < 1
        'provider_name = "x"\nconformance_level = "2"\n',  # non-int level
        'provider_name = "x"\nconformance_level = true\n',  # bool is not a level
        'provider_name = "x"\nconformance_level = 3\n',  # above harness-supported max
    ],
)
def test_selftest_profile_loader_rejects_invalid(tmp_path, body) -> None:
    f = tmp_path / "bad.toml"
    f.write_text(body)
    load_profile.cache_clear()
    with pytest.raises(SystemExit):
        load_profile(f)


def test_selftest_config_schema_envelope_validator() -> None:
    # Prove the real validator the executable-profile suite runs
    # (checks.assert_config_schema_envelope): a good envelope passes; every
    # malformed shape is rejected. Pure string in -> validator; no fake binary.
    import json

    good = json.dumps(
        {
            "config_schema_version": 1,
            "provider": "anolis-provider-x",
            "schema": {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"},
        }
    )
    assert_config_schema_envelope(good)  # must NOT raise

    for bad in (
        "not json",  # unparseable
        json.dumps([1, 2, 3]),  # top-level not an object
        json.dumps({"schema": {"type": "object"}}),  # missing version
        json.dumps({"config_schema_version": 0, "schema": {}}),  # version < 1
        json.dumps({"config_schema_version": True, "schema": {}}),  # bool is not a version
        json.dumps({"config_schema_version": "1", "schema": {}}),  # non-int version
        json.dumps({"config_schema_version": 1}),  # missing schema
        json.dumps({"config_schema_version": 1, "schema": "x"}),  # schema not an object
    ):
        with pytest.raises(ConformanceFailure):
            assert_config_schema_envelope(bad)


def test_selftest_check_host_envelope_validator() -> None:
    # Prove the real validator the executable-profile suite runs
    # (checks.assert_check_host_envelope): well-formed envelopes with a matching
    # exit code pass; every malformed shape, and every exit code that disagrees
    # with the statuses, is rejected. Pure string + code in; no fake binary.
    import json

    def env(reqs, **extra):
        return json.dumps({"check_host_version": 1, "provider": "anolis-provider-x", "requirements": reqs, **extra})

    met = {"id": "bus.present", "status": "met", "detail": "/dev/i2c-1 exists"}
    unmet = {"id": "bus.access", "status": "unmet", "detail": "permission denied", "remedy": "add the user to group i2c"}
    unknown = {"id": "bus.clock", "status": "unknown", "detail": "clock not exposed on this platform"}

    for good, code in (
        (env([]), 0),  # nothing to check (e.g. a mock config)
        (env([met]), 0),
        (env([met, unknown]), 0),  # unknown is not unmet
        (env([met, unmet]), 1),
        (env([unmet], extra_key="provider-specific"), 1),  # extra keys allowed
    ):
        assert_check_host_envelope(good, code)  # must NOT raise

    for bad, code in (
        ("not json", 0),  # unparseable
        (json.dumps([met]), 0),  # top-level not an object
        (json.dumps({"requirements": []}), 0),  # missing version
        (json.dumps({"check_host_version": 0, "requirements": []}), 0),  # version < 1
        (json.dumps({"check_host_version": True, "requirements": []}), 0),  # bool is not a version
        (json.dumps({"check_host_version": 1}), 0),  # missing requirements
        (json.dumps({"check_host_version": 1, "requirements": {}}), 0),  # requirements not an array
        (env(["bus.present"]), 0),  # requirement not an object
        (env([{"status": "met"}]), 0),  # missing id
        (env([{"id": "", "status": "met"}]), 0),  # empty id
        (env([{"id": "bus.present", "status": "ok"}]), 0),  # status outside met/unmet/unknown
        (env([{"id": "bus.present"}]), 0),  # missing status
        (env([met]), 1),  # exit 1 with nothing unmet
        (env([unmet]), 0),  # exit 0 with something unmet
        (env([met]), 2),  # exit 2 is not an answer for a valid config
    ):
        with pytest.raises(ConformanceFailure):
            assert_check_host_envelope(bad, code)
