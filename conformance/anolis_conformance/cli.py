"""Console entry point: ``anolis-adpp-conformance`` -> pytest over this package."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    import pytest

    # Load the plugin explicitly (it is intentionally not a global pytest11 entry
    # point — see pyproject.toml). The plugin applies the default gating marker
    # filter, so this entry point and direct `pytest -p` use select the same set.
    args = list(sys.argv[1:] if argv is None else argv)
    base = ["-p", "anolis_conformance.plugin", "--pyargs", "anolis_conformance"]
    return pytest.main([*base, *args])


if __name__ == "__main__":
    raise SystemExit(main())
