"""Anolis *provider executable profile* — conventions the Anolis runtime/tooling
expects of a provider binary, distinct from ADPP wire conformance: the CLI
surface, the WaitReady diagnostics the runtime reads, and process lifecycle.

Normative source: ``docs/profiles/anolis-executable-profile-v1.md`` — an
organizational acceptance profile, NOT ADPP conformance. A binary can be
ADPP-conformant and still diverge here; such gaps are declared as xfails in the
provider's own `--provider-profile` manifest (see profiles.py for the schema).
"""

from __future__ import annotations

import re
import subprocess

import pytest

from .checks import (
    assert_check_host_envelope,
    assert_config_schema_envelope,
    assert_function_ids_per_type_from_one,
    assert_signal_ids_snake_case,
    check_host_implemented,
)
from .client import AdppClient

# Every test here is an Anolis executable-profile convention — the only tests a
# provider's --provider-profile waiver is permitted to xfail.
pytestmark = pytest.mark.executable_profile


def _device_capabilities(client: AdppClient):
    """[(device_id, CapabilitySet)] for every device the provider exposes."""
    client.hello()
    out = []
    for d in client.list_devices().list_devices.devices:
        caps = client.describe_device(d.device_id).describe_device.capabilities
        out.append((d.device_id, caps))
    return out


# ---- readiness diagnostics ---------------------------------------------
def test_wait_ready_reports_init_time_ms(client: AdppClient, codes, status_text) -> None:
    # The runtime reads `init_time_ms` from WaitReady diagnostics. (Standardized
    # key set; not an ADPP wire requirement.)
    resp = client.hello()
    if resp.hello.metadata.get("supports_wait_ready") != "true":
        pytest.skip("provider does not advertise supports_wait_ready")
    wr = client.wait_ready()
    assert wr.status.code == codes.OK, status_text(wr)
    diags = dict(wr.wait_ready.diagnostics)
    assert "init_time_ms" in diags, f"wait_ready should report init_time_ms; got {sorted(diags)}"


# ---- capability conventions ---------------------------------------------
def test_signal_ids_snake_case(client: AdppClient) -> None:
    # Convention: signal_id is snake_case (see the executable profile, §5).
    caps = _device_capabilities(client)
    if not caps:
        pytest.skip("provider exposes no devices")
    for device_id, capabilities in caps:
        assert_signal_ids_snake_case(device_id, capabilities)


def test_function_ids_per_type_from_one(client: AdppClient) -> None:
    # Convention: each device's function_ids are per-type {1..N} (see §5).
    caps = _device_capabilities(client)
    if not caps:
        pytest.skip("provider exposes no devices")
    for device_id, capabilities in caps:
        assert_function_ids_per_type_from_one(device_id, capabilities)


# ---- process hygiene ----------------------------------------------------
def test_clean_shutdown_on_stdin_eof(client: AdppClient) -> None:
    client.hello()
    code = client.close(timeout=5.0)  # closes stdin -> EOF
    assert code == 0, f"provider must exit 0 on stdin EOF; got {code}\n{client.output_tail(40)}"


# ---- CLI ----------------------------------------------------------------
def test_cli_version_flag(provider_bin) -> None:
    proc = subprocess.run([str(provider_bin), "--version"], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0, f"`--version` must exit 0; got {proc.returncode} ({proc.stderr[:200]})"
    # Require a dotted version token (e.g. 1.2.0), not merely "some digit
    # somewhere" — unrelated diagnostic output must not satisfy --version.
    assert re.search(r"\d+\.\d+", proc.stdout), (
        f"`--version` should print a version like X.Y[.Z]; got {proc.stdout!r}"
    )


def test_cli_check_config_ok(provider_bin, provider_config) -> None:
    proc = subprocess.run(
        [str(provider_bin), "--check-config", str(provider_config)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert proc.returncode == 0, f"`--check-config` on a valid config must exit 0; got {proc.returncode}"


def test_cli_config_schema(provider_bin) -> None:
    # `--config-schema` is configless (§2). If the provider does not recognize the
    # verb it exits non-zero (a usage error) — SKIP, no waiver needed: this is how
    # the convention adopts with zero coordination. If it exits 0 the envelope MUST
    # be valid.
    proc = subprocess.run([str(provider_bin), "--config-schema"], capture_output=True, text=True, timeout=10)
    if proc.returncode != 0:
        pytest.skip("provider does not implement --config-schema (unrecognized verb)")
    assert_config_schema_envelope(proc.stdout)


def test_cli_check_host(provider_bin, provider_config) -> None:
    # `--check-host <config>` (§6). A provider without the verb rejects it as a
    # usage error — non-zero, and no JSON on stdout (shipped providers print their
    # usage text there) — and is SKIPPED, no waiver needed, as for --config-schema.
    # Once it answers, the envelope MUST be valid and the exit code MUST agree with
    # the statuses. Whether the harness host meets the requirements is not
    # asserted: either answer is valid.
    proc = subprocess.run(
        [str(provider_bin), "--check-host", str(provider_config)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if not check_host_implemented(proc.stdout, proc.returncode):
        pytest.skip("provider does not implement --check-host (usage error, no JSON on stdout)")
    assert_check_host_envelope(proc.stdout, proc.returncode)
