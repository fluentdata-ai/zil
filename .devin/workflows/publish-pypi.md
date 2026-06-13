---
description: Build and publish the zil-ai package to PyPI
---

# Publish zil-ai to PyPI

## Prerequisites

- PyPI API token stored in `~/.pypirc` or available as env var `TWINE_PASSWORD`
- `build` and `twine` installed in the dev venv (`pip install build twine`)

## Steps

1. Run all tests to make sure everything passes:
// turbo
```bash
cd /Users/jdiaz/wdir/zil && .venv/bin/python -m pytest tests/ -v
```

2. Run linting:
// turbo
```bash
cd /Users/jdiaz/wdir/zil && .venv/bin/python -m ruff check src/
```

3. Bump the version in `pyproject.toml` — ask the user what the new version should be. Update the `version` field under `[project]` **and** the `__version__` in `src/zil/__init__.py` to match.

4. Update the changelog (`CHANGELOG.md`):
   a. Get commits since the last git tag:
   // turbo
   ```bash
   cd /Users/jdiaz/wdir/zil && git log --oneline --no-merges $(git describe --tags --abbrev=0 2>/dev/null || echo "")..HEAD
   ```
   b. Add a new `## [<VERSION>] — <DATE>` section at the top of the changelog (below the header), using the commit list as reference. Categorize entries under `### Added`, `### Changed`, `### Fixed`, or `### Removed` as appropriate. Write human-readable descriptions, not raw commit messages.
   c. Add the comparison link at the bottom of the file: `[<VERSION>]: https://github.com/fluentdata-co/zil/compare/v<PREV>...v<VERSION>`.
   d. Show the user the new changelog entry and ask them to confirm or request edits.
   e. Copy the updated content to `docs/app/changelog/page.mdx`, keeping the MDX header and converting `[version]` reference links to inline links.

5. Clean previous build artifacts:
// turbo
```bash
cd /Users/jdiaz/wdir/zil && rm -rf dist/ build/ src/*.egg-info
```

6. Build the sdist and wheel:
```bash
cd /Users/jdiaz/wdir/zil && .venv/bin/python -m build
```

7. Verify the built package looks correct:
// turbo
```bash
cd /Users/jdiaz/wdir/zil && ls -lh dist/ && .venv/bin/python -m twine check dist/*
```

8. Upload to PyPI:
```bash
cd /Users/jdiaz/wdir/zil && .venv/bin/python -m twine upload dist/*
```

9. Verify the published package:
```bash
pip index versions zil-ai
```

10. Update documentation:
    a. Review all docs pages under `docs/app/` for any content that references the previous version or needs updating based on the changes in this release (e.g., new features, changed APIs, updated CLI output).
    b. Update the version shown in `docs/app/getting-started/page.mdx` (the `zil --version` output).
    c. If the major/minor version changed, update the version badge in `docs/app/layout.tsx` (the `v0.1 draft` badge in the navbar).
    d. Update `docs/agent-content.txt` (served at `getzil.dev/docs/agent.txt`) to reflect any CLI, SDK, manifest, or feature changes in this release. This is the agent-friendly plain-text reference and must stay in sync.
    e. Build the docs to verify:
    // turbo
    ```bash
    cd /Users/jdiaz/wdir/zil/docs && pnpm build 2>&1 | grep -E "(✓|Error|error|Indexed)"
    ```

11. Commit, tag, and push:
```bash
cd /Users/jdiaz/wdir/zil && git add -A && git commit -m "Release v<VERSION>"
```
```bash
cd /Users/jdiaz/wdir/zil && git tag v<VERSION>
```
```bash
cd /Users/jdiaz/wdir/zil && git push origin main v<VERSION>
```

12. Deploy docs to production:
```bash
cd /Users/jdiaz/wdir/zil/docs && vercel --prod
```
