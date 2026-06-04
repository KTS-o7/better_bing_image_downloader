# AGENTS.md

Notes for AI coding agents (Claude, GPT, Cursor, etc.) working in this
repository. Read this before making non-trivial changes.

## Project at a glance

- **What it is:** Python library + `bbid` CLI for bulk-downloading
  images from Bing or DuckDuckGo.
- **Python:** 3.8+. Pure-stdlib HTTP (urllib), optional `brotli` for
  DuckDuckGo, optional `selenium` for the legacy `multidownloader` path.
- **No CI is configured** (per the maintainer's request). Lint/type/test
  is run locally before pushing.
- **Tests:** 72 passing, 1 network test skipped by default
  (`BBID_RUN_NETWORK_TESTS=1` to enable).
- **Linters:** `black` (formatter), `ruff` (lint), `mypy` (types).
  All three run via pre-commit.

## File map

| File | What it does | Modify freely? |
|------|--------------|----------------|
| `base.py` | `ImageEngine` base class — atomic write, dedup, resume, manifest, parallel downloads, future timeout | ✅ Yes |
| `bing.py` | Bing image search engine (inherits from `base.ImageEngine`) | ✅ Yes |
| `duckduckgo.py` | DuckDuckGo image search engine (inherits from `base.ImageEngine`) | ✅ Yes |
| `download.py` | Public `downloader()` function, `bbid` CLI, engine dispatch | ✅ Yes |
| `__init__.py` | Public API surface | ✅ Yes |
| `crawler.py` | **DEPRECATED** Selenium-based crawler | ⚠️ Don't extend; remove in v4.0.0 |
| `multidownloader.py` | **DEPRECATED** Selenium-based CLI | ⚠️ Don't extend; remove in v4.0.0 |
| `helperdownload.py` | **DEPRECATED** Used by `multidownloader` | ⚠️ Don't extend; remove in v4.0.0 |
| `utils.py` | **DEPRECATED** Config helpers | ⚠️ Don't extend; remove in v4.0.0 |
| `pyproject.toml` | Package metadata, version, tool config | ✅ Yes (bump version on release) |
| `requirements*.txt` | Mirror of `[project.optional-dependencies]` | ✅ Yes |
| `tests/` | pytest test suite | ✅ Yes |
| `README.md` | User docs | ✅ Yes |
| `CHANGELOG.md` | Release notes | ✅ Yes (add an "Unreleased" section) |
| `CONTRIBUTING.md` | Contributor guide | ✅ Yes |
| `.pre-commit-config.yaml` | Pre-commit hook config | ✅ Yes (pin revisions carefully) |

## Patterns and conventions

### Adding a new feature

1. **Read `base.py` first.** Most download-side concerns are already
   handled there. New features should reuse `download_image()` and
   `_download_batch()` instead of duplicating the parallel-download
   logic.
2. **TDD where possible.** The existing tests mock at module-attribute
   boundaries (`urllib.request.urlopen`, `filetype.guess`,
   `requests.get`). Follow the pattern in `tests/test_duckduckgo.py`.
3. **No new top-level dependencies** without discussion. The package
   has stayed stdlib-only for the Bing path; optional extras are
   `[duckduckgo]` (brotli) and `[google]` (selenium).

### Test patterns

- Tests use `pytest` (not unittest, except `tests/test_bing.py` which
  was written in unittest style — both work, prefer pytest for new
  tests).
- Patches target the **module that uses** the symbol, not the symbol's
  origin. Example: `filetype` is imported in `base.py`, so patch
  `better_bing_image_downloader.base.filetype.guess`, not
  `better_bing_image_downloader.bing.filetype.guess`.
- Network tests must be gated on `BBID_RUN_NETWORK_TESTS=1`.
- The end-to-end DDG test is the only network test today. Add new
  end-to-end tests behind the same gate.

### Commit messages

Use [Conventional Commits](https://www.conventionalcommits.org/):
`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`. Scope is
optional but useful (`feat(duckduckgo): add region code`).

### Versioning

- **Patch** (3.1.x): bug fixes, no API change.
- **Minor** (3.x.0): new features, backwards-compatible.
- **Major** (x.0.0): breaking changes.

The current version is **3.1.0**. Bump in `pyproject.toml` and
`CHANGELOG.md` when cutting a release. Releases are cut by:
1. Committing on `main`.
2. Tagging (`git tag -a v3.X.Y -m "v3.X.Y: summary"`).
3. Pushing the tag.
4. Creating a GitHub release — the `python-publish.yml` workflow
   publishes to PyPI automatically.

### Code style

- **Line length:** 100 (enforced by black + ruff).
- **Type hints:** required on public API. `base.py`, `bing.py`,
  `duckduckgo.py`, and `download.py` are typed; deprecated modules
  are not.
- **Docstrings:** Google-style or NumPy-style; the existing code mixes
  both. Match the style of the file you're editing.
- **Logging:** use `logging`, never `print()`. The `helperdownload`
  migration to `logging` was a deliberate fix; don't reintroduce
  `print()` calls.

## What NOT to do

- **Don't reintroduce `print()` in library code.** It's a library; users
  may pipe stdout.
- **Don't add Selenium or other browser-automation deps to the core.**
  The Google path is dead; don't try to revive it.
- **Don't use `requests` for new code in `bing.py` or `duckduckgo.py`.**
  They use `urllib.request` so the Bing path stays stdlib-only.
  `helperdownload` (deprecated) uses `requests`; don't copy that
  pattern into new code.
- **Don't silently change return types or signatures** on
  `downloader()`, `Bing`, or `DuckDuckGo`. Add a new parameter with a
  default value instead.
- **Don't commit `dist/`, `build/`, `__pycache__/`, or `.venv/`.**
  The `.gitignore` should already cover these, but double-check
  before committing.

## Common tasks

### "I want to add a new search engine"

1. Create `better_bing_image_downloader/myengine.py` with a class
   that subclasses `base.ImageEngine`.
2. Implement `__init__` to validate engine-specific options.
3. Implement `run()` to fetch URL pages and call
   `self._download_batch(links, start_index=self.download_count + 1)`.
4. Add the engine to `_build_engine()` in `download.py`.
5. Add `--engine myengine` to the CLI argparse choices in `main()`.
6. Add tests in `tests/test_myengine.py` mirroring `test_duckduckgo.py`.
7. Add a "Search engines" section to `README.md`.

### "I want to fix a bug"

1. Reproduce with a failing test in `tests/`.
2. Fix the bug.
3. Confirm `pytest` passes.
4. Run `pre-commit run --all-files` to catch lint/type regressions.

### "I want to bump the version and release"

1. Update `CHANGELOG.md` — move "Unreleased" entries under a dated
   version heading.
2. Bump `version` in `pyproject.toml`.
3. Commit on `main`.
4. Tag: `git tag -a v3.X.Y -m "v3.X.Y: <one-line summary>"`.
5. Push: `git push origin main --follow-tags`.
6. Create a GitHub release with notes from `CHANGELOG.md` (use
   `gh release create v3.X.Y --notes-file <(sed -n '/^## \[3.X.Y\]/,/^## /p' CHANGELOG.md | head -n -2)`).
7. The `python-publish.yml` workflow will publish to PyPI.
8. Verify on https://pypi.org/project/better-bing-image-downloader/.

## Verifying your work

Before pushing:

```bash
pytest                                          # 72 tests should pass
pre-commit run --all-files                      # black, ruff, mypy clean
python -m build && twine check dist/*           # package metadata valid
```

If you added a CLI flag, also smoke-test it:

```bash
bbid --help
bbid --engine duckduckgo --limit 2 "red panda"  # or whatever you added
```
