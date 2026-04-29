# Publishing red-crawler

This repo publishes the `red-crawler` Python package, which exposes the `red-crawler` CLI entry point.

## Preflight

Run the full test suite and build both distribution formats:

```bash
uv run pytest -q
rm -rf dist
uv build
```

Expected artifacts:

- `dist/red_crawler-0.1.3-py3-none-any.whl`
- `dist/red_crawler-0.1.3.tar.gz`

Smoke-test the wheel in a clean temporary environment before uploading:

```bash
tmpdir="$(mktemp -d)"
python3 -m venv "$tmpdir/venv"
"$tmpdir/venv/bin/python" -m pip install dist/red_crawler-0.1.3-py3-none-any.whl
"$tmpdir/venv/bin/red-crawler" --version
"$tmpdir/venv/bin/red-crawler" --help
```

The Playwright browser runtime is intentionally not bundled in the wheel. Users install it after installing the CLI:

```bash
red-crawler install-browsers
```

## TestPyPI

Publish to TestPyPI first:

```bash
uv publish --publish-url https://test.pypi.org/legacy/ dist/*
```

Then install from TestPyPI in a clean environment:

```bash
uv tool install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ red-crawler==0.1.3
red-crawler --version
```

## PyPI

After the TestPyPI package installs and the CLI starts:

```bash
uv publish dist/*
```

Use an API token from PyPI or TestPyPI through the standard `UV_PUBLISH_TOKEN` environment variable or interactive prompt.
