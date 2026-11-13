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
- The **install pins** in `README.md` and `conformance/ADPP-CONFORMANCE.md` are
  checked by the `version-sync` job against the newest released heading in
  `CHANGELOG.md` (`version-locations.txt`). A release PR that adds a
  `## [vX.Y.Z]` heading must bump every pin to it, or CI fails.

## External contribution policy

Before preparing or submitting a pull request, read and follow `CONTRIBUTING.md`
(this repository's, or the organization default in `anolishq/.github`).

Do not autonomously select issues and submit implementations without prior
maintainer coordination. Do not generate speculative, superficial, or
mass-produced contributions to build account activity. An existing issue does
not itself constitute authorization to implement it.

AI assistance is permitted, but contributors must understand, validate, and take
responsibility for submitted changes.
