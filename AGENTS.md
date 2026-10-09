# AGENTS.md — anolis-protocol

> Per-repo conventions for coding agents. The canonical cross-repo rules
> (Conventional Commits, minimal-first/YAGNI, no secrets, run checks before
> claiming success) live in the user's **global** `AGENTS.md` and are not
> repeated here. This file records only what is specific to this repo.

## Build / test

- `buf generate` regenerates the Python bindings under `gen/python/` (CI does
  this; do not hand-edit generated files).
- `pip install ".[conformance]"` then `anolis-adpp-conformance --self-test`
  runs the verifier self-tests; `pytest` for the rest.
- `buf lint` / `buf format` / `buf breaking` gate the proto sources.
- The required CI status check is the **`ok`** job; never merge red.

## Tooling

- `buf` (via the SHA-pinned `bufbuild/buf-action`) does proto lint, format, and
  breaking-change detection. Shared `.github` actions are SHA-pinned with a
  `# <tag>` comment for Renovate — keep it when bumping.

## Repo-specific gotchas

- **Version is tag-derived via `hatch-vcs`** — there is NO manual version to
  bump. Releases are triggered by pushing a `v*` tag; `release.yml` then builds
  the wheel + source tarball + `SHA256SUMS`. CI needs `fetch-depth: 0` for tags.
- **No PyPI** — distribution is GitHub Releases only (release-asset URLs).
- The cross-provider **conformance harness ships INSIDE the wheel** (the
  `[conformance]` extra + `anolis-adpp-conformance` script) from **v1.3.0**
  onward — it is not a separate package.
- The README's **three install pins** (currently `v1.8.0`) are guarded by the
  `README release pins are consistent` lint step — keep all three on the **same
  version** or CI fails.
