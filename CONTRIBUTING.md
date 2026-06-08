# Contributing to better-bing-image-downloader

Thanks for your interest in contributing! This guide covers how to set
up a development environment, run the tests, and submit a pull request.

## Development setup

We recommend working in a Python virtual environment:

```bash
git clone https://github.com/KTS-o7/better_bing_image_downloader
cd better_bing_image_downloader
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install the package in editable mode with all dev + optional extras
pip install -e ".[dev]"

# Install the pre-commit hooks
pre-commit install
```

The `[dev]` extra pulls in pytest, black, ruff, mypy, and pre-commit.
`brotli` is a hard runtime dependency as of v3.1.1, so no extra is
needed to test the DuckDuckGo engine locally.

## Running tests

```bash
# Run the full test suite (123 tests, 2 network tests skipped by default)
pytest

# Run with coverage
pytest --cov=better_bing_image_downloader

# Run the live DuckDuckGo end-to-end tests (requires network)
BBID_RUN_NETWORK_TESTS=1 pytest tests/test_duckduckgo.py -k EndToEnd
BBID_RUN_NETWORK_TESTS=1 pytest tests/test_v3_2_0_integration.py
```

Tests live in `tests/`. New code should come with new tests; the
project follows a TDD-friendly style with mocks so most tests run
without network access.

## Linting and formatting

Pre-commit hooks run `black`, `ruff`, and `mypy` on every commit. To
run them manually on all files:

```bash
pre-commit run --all-files
```

Or run the tools individually:

```bash
black better_bing_image_downloader/ tests/
ruff check --fix better_bing_image_downloader/ tests/
mypy
```

Configuration lives in `pyproject.toml` under `[tool.black]`,
`[tool.ruff]`, and `[tool.mypy]`.

## Project structure

```
better_bing_image_downloader/
├── base.py             # ImageEngine ABC (download, dedup, resume, manifest, hooks)
├── bing.py             # Bing image search engine
├── crawler.py          # [DEPRECATED] Selenium-based crawler (will be removed in v4)
├── download.py         # Legacy downloader() function and bbid CLI
├── downloader.py       # Downloader class — v3.2.0+ library entry point
├── duckduckgo.py       # DuckDuckGo image search engine
├── helperdownload.py   # [DEPRECATED] Concurrent URL-list downloader
├── multidownloader.py  # [DEPRECATED] Selenium-based CLI
├── results.py          # Result and ImageResult value objects
├── utils.py            # [DEPRECATED] Config helpers
└── py.typed            # PEP 561 marker — types are exported
```

If you're adding a new feature, look at `base.py` (shared download
logic) and `downloader.py` (the public embeddable façade) first.
New code should add a new method to `Downloader` or a new hook,
not extend the legacy `downloader()` function.

## Commit conventions

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add support for Yandex image search
fix: handle empty page results without infinite loop
docs: clarify engine parameter on downloader()
test: add coverage for atomic write failure path
refactor: extract atomic write into helper
chore: bump version to 3.2.0
```

The format is `<type>(<scope>): <description>`. Common scopes:
`bing`, `duckduckgo`, `cli`, `tests`, `docs`, `release`. The first
line stays under 72 characters; the body, if any, is wrapped at 72.

## Pull request process

1. **Create a feature branch** off `main`:
   ```bash
   git checkout -b feat/my-feature
   ```

2. **Write tests first** (or alongside your change) — see
   `tests/test_atomic_write.py` for the established pattern.

3. **Make sure all checks pass locally**:
   ```bash
   pytest
   pre-commit run --all-files
   ```

4. **Update the CHANGELOG.md** under the "Unreleased" section if your
   change is user-facing (added option, bug fix, deprecation).

5. **Push and open a PR** against `main`:
   ```bash
   git push origin feat/my-feature
   gh pr create --fill
   ```

6. The maintainer will review and may request changes. Squash-merge is
   the default.

## Adding a new search engine

To add a new first-class engine (e.g. Yandex, Brave):

1. Create `better_bing_image_downloader/myengine.py` with a class that
   subclasses `base.ImageEngine`.
2. Implement `__init__` to validate engine-specific options and
   `run()` to fetch URLs and call `self._download_batch()` /
   `self.download_image()`.
3. Register the engine in `Downloader._DEFAULT_REGISTRY` in
   `downloader.py` (so it's a first-class engine exposed by
   default). Third-party engines should be registered at runtime
   via `Downloader.register("myengine", MyEngineClass)` instead.
4. Expose the engine name in `main()` argparse choices
   (`--engine myengine`) in `download.py` (only for first-class
   engines).
5. Add tests under `tests/test_myengine.py` mirroring the structure
   of `tests/test_duckduckgo.py`.
6. Update the README with a new "Search engines" section.

The base class handles all the download-side concerns (atomic writes,
MD5 dedup, resume, manifest, parallel workers, timeouts, exponential
backoff). Your engine subclass only needs to fetch URL lists and
update `self.download_count` / `self._slots_used` as it goes (the
`Downloader` class wires your engine's `save_image` to fire the
`on_image` hook and populate the `Result.images` list).

## Release process

Maintainers cut releases as follows:

1. Update `CHANGELOG.md` — move "Unreleased" entries under a dated
   version heading.
2. Bump `version` in `pyproject.toml`.
3. Commit on `main` (no PR needed for the version bump itself, but
   all features should already be merged via PR).
4. Tag: `git tag -a v3.X.Y -m "v3.X.Y: <one-line summary>"`.
5. Push the branch and the tag:
   `git push origin main --follow-tags`.
6. Create a GitHub release with notes from `CHANGELOG.md`. Use
   `gh release create v3.X.Y --notes-file <(awk '/^## \[3.X.Y\]/{flag=1} /^## \[3.X.Y-1\]/{flag=0} flag' CHANGELOG.md)`.
7. The `python-publish.yml` workflow will build and upload to PyPI
   automatically. Verify on
   <https://pypi.org/project/better-bing-image-downloader/>.

## Questions?

Open a GitHub issue or email
[shentharkrishnatejaswi@gmail.com](mailto:shentharkrishnatejaswi@gmail.com).
