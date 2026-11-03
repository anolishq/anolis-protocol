"""pytest wiring for the cross-provider ADPP conformance suite.

This plugin is NOT auto-registered as a global pytest11 entry point (that would
add Anolis-only options + an autouse fixture to every unrelated pytest run).
Load it explicitly: the console script does `-p anolis_conformance.plugin`, and
an uninstalled checkout runs `pytest -p anolis_conformance.plugin ...`.

Two explicit modes (a misconfigured run must never exit 0 having tested nothing):

* **provider mode** — all three of ``--provider-bin``/``--provider-config``/
  ``--provider-profile`` are required; the provider contract tests run.
* **self-test mode** (``--self-test``) — only the hermetic verifier self-tests
  run, against in-repo fake providers; no provider args allowed.

Supplying neither (or a partial set of provider args) is a usage error.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from .client import AdppClient
from .profiles import load_profile

_PROVIDER_OPTS = ("--provider-bin", "--provider-config", "--provider-profile")


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "experimental: opt-in/non-gating checks (run with `-m experimental`)."
    )
    config.addinivalue_line(
        "markers",
        "executable_profile: Anolis executable-profile convention (the only tests a "
        "provider waiver may xfail).",
    )
    config.addinivalue_line(
        "markers",
        "conformance_level(n): runs only when the provider's declared conformance_level "
        ">= n. Untagged tests are level 1.",
    )

    # The gating set excludes experimental checks unless the caller selects
    # markers with -m. Applied here, not in the console script, so loading the
    # plugin directly (`pytest -p anolis_conformance.plugin`) gates the same set.
    if not config.option.markexpr:
        config.option.markexpr = "not experimental"

    self_test = config.getoption("--self-test")
    present = [opt for opt in _PROVIDER_OPTS if config.getoption(opt)]

    if self_test:
        if present:
            raise pytest.UsageError(
                f"--self-test runs only the hermetic verifier tests and takes no "
                f"provider args (got {', '.join(present)})."
            )
        config._adpp_mode = "self-test"  # type: ignore[attr-defined]
        return

    if not present:
        raise pytest.UsageError(
            "no mode selected: pass --self-test for the verifier self-tests, or all of "
            f"{'/'.join(_PROVIDER_OPTS)} to run a provider through conformance."
        )

    missing = [opt for opt in _PROVIDER_OPTS if not config.getoption(opt)]
    if missing:
        raise pytest.UsageError(
            f"provider conformance requires {', '.join(_PROVIDER_OPTS)}; missing "
            f"{', '.join(missing)}. A partial invocation must not appear conformant."
        )
    config._adpp_mode = "provider"  # type: ignore[attr-defined]


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("adpp-conformance")
    group.addoption("--provider-bin", action="store", help="Path to the provider executable.")
    group.addoption("--provider-config", action="store", help="Path to the provider config (mock-mode for CI).")
    group.addoption(
        "--provider-profile",
        action="store",
        help="Path to the provider's conformance manifest (TOML: identity + waivers, "
        "owned by the provider repo).",
    )
    group.addoption(
        "--self-test",
        action="store_true",
        default=False,
        help="Run only the hermetic verifier self-tests (no provider args).",
    )
    group.addoption(
        "--provider-extra-arg",
        action="append",
        default=[],
        help="Extra CLI arg to pass to the provider (repeatable).",
    )


def _mode(config: pytest.Config) -> str:
    return getattr(config, "_adpp_mode", "provider")


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Restrict collection to the active mode, then validate waiver scope."""
    self_test = _mode(config) == "self-test"
    selected, deselected = [], []
    for item in items:
        is_selftest = item.path.name == "test_selftest.py"
        (selected if is_selftest == self_test else deselected).append(item)
    if deselected:
        config.hook.pytest_deselected(items=deselected)
        items[:] = selected

    if self_test:
        return

    # Provider mode: a waiver may only target an executable_profile test. Reject
    # unknown/out-of-scope keys (typos, or an attempt to mask a core/transport
    # failure) before any test runs.
    raw = config.getoption("--provider-profile")
    profile = load_profile(Path(raw))
    waivable = {
        item.originalname  # type: ignore[attr-defined]
        for item in items
        if item.get_closest_marker("executable_profile") is not None
    }
    unknown = set(profile.known_xfails) - waivable
    if unknown:
        raise pytest.UsageError(
            f"--provider-profile waivers reference non-executable-profile tests "
            f"{sorted(unknown)}; waivers may only target executable_profile tests "
            f"({sorted(waivable)}). Waivers must never mask core/transport/verifier failures."
        )

    # Conformance-level gating: a test marked conformance_level(n) runs only when
    # the provider declares level >= n. Untagged tests are level 1. This is what
    # makes a declared level actually run its extra requirements (not the
    # experimental marker).
    above_level = []
    for item in items:
        marker = item.get_closest_marker("conformance_level")
        required = marker.args[0] if marker and marker.args else 1
        if required > profile.conformance_level:
            above_level.append(item)
    if above_level:
        config.hook.pytest_deselected(items=above_level)
        skip = set(above_level)
        items[:] = [i for i in items if i not in skip]


@pytest.fixture(scope="session")
def protocol():
    """The generated ADPP protobuf module (shipped by the anolis-protocol wheel)."""
    return importlib.import_module("protocol_pb2")


@pytest.fixture(scope="session")
def codes(protocol):
    """ADPP Status.Code values resolved from the proto enum (e.g. codes.NOT_FOUND)."""
    from . import spec

    return spec.resolve_codes(protocol)


@pytest.fixture(scope="session")
def status_text(protocol):
    """A `(resp) -> str` describer using the proto enum names."""
    from . import spec

    return lambda resp: spec.status_text(protocol, resp)


@pytest.fixture(scope="session")
def profile(request: pytest.FixtureRequest):
    raw = request.config.getoption("--provider-profile")
    if not raw:
        pytest.skip("conformance test requires --provider-profile (a provider-owned manifest)")
    return load_profile(Path(raw))


@pytest.fixture(scope="session")
def provider_bin(request: pytest.FixtureRequest) -> Path:
    raw = request.config.getoption("--provider-bin")
    if not raw:
        pytest.skip("conformance test requires --provider-bin")
    path = Path(raw)
    if not path.exists():
        pytest.fail(f"--provider-bin not found: {path}")
    return path


@pytest.fixture(scope="session")
def provider_config(request: pytest.FixtureRequest) -> Path:
    raw = request.config.getoption("--provider-config")
    if not raw:
        pytest.skip("conformance test requires --provider-config")
    path = Path(raw)
    if not path.exists():
        pytest.fail(f"--provider-config not found: {path}")
    return path


@pytest.fixture(scope="session")
def provider_extra_args(request: pytest.FixtureRequest) -> list[str]:
    return list(request.config.getoption("--provider-extra-arg"))


@pytest.fixture
def client(protocol, provider_bin, provider_config, provider_extra_args):
    """A freshly-spawned provider per test (isolation: tests may corrupt the session)."""
    c = AdppClient(protocol, provider_bin, provider_config, extra_args=provider_extra_args)
    try:
        yield c
    finally:
        c.close()


@pytest.fixture
def ready_client(client, codes, status_text):
    """A client past the Hello (+ WaitReady, derived from advertised metadata) handshake."""
    from .checks import assert_status_present

    resp = client.hello()
    assert_status_present(resp)
    assert resp.status.code == codes.OK, status_text(resp)
    if resp.hello.metadata.get("supports_wait_ready") == "true":
        wr = client.wait_ready()
        assert wr.status.code == codes.OK, f"wait_ready failed: {status_text(wr)}"
    return client


@pytest.fixture(autouse=True)
def _apply_known_xfails(request: pytest.FixtureRequest) -> None:
    """Apply a provider's tracked executable-profile gaps as **strict** xfails.

    No-ops outside provider mode (so the verifier self-tests and unrelated suites
    are unaffected). Waivers apply ONLY to executable_profile tests — scope is
    validated up front in pytest_collection_modifyitems — and are strict so a
    fixed divergence fails (XPASS) until its waiver is removed.
    """
    raw = request.config.getoption("--provider-profile", default=None)
    if not raw or request.node.get_closest_marker("executable_profile") is None:
        return
    reason = load_profile(Path(raw)).xfail_reason(request.node.originalname)
    if reason:
        request.node.add_marker(pytest.mark.xfail(reason=reason, strict=True, run=True))
