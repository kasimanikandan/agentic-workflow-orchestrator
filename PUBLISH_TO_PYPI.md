# Publishing Orchestrator SDK to PyPI

Complete guide to build and publish `agentic-workflow-orchestrator` to PyPI.

---

## Prerequisites

Install build tools:

```bash
pip install --upgrade build twine setuptools wheel
```

---

## Step 1: Verify Package Structure

```bash
cd /Users/manikandankasi/Desktop/mani/dev/orchestrator/sdk-python

# Check structure
ls -la
# Should show:
#   orchestrator/        — main package
#   tests/              — test suite
#   examples/           — example workflows
#   pyproject.toml      — build config (modern)
#   setup.py            — build config (backward compat)
#   MANIFEST.in         — include non-Python files
#   README.md           — package description
#   CHANGELOG.md        — version history

# Verify orchestrator package has __init__.py
ls orchestrator/__init__.py
```

---

## Step 2: Update Version Number

Edit `pyproject.toml` and `setup.py`:

**pyproject.toml:**
```toml
version = "0.1.0"  # Change this
```

**setup.py:**
```python
version="0.1.0",  # Change this
```

---

## Step 3: Build the Distribution

```bash
cd /Users/manikandankasi/Desktop/mani/dev/orchestrator/sdk-python

# Clean previous builds
rm -rf build dist *.egg-info

# Build source distribution + wheel
python -m build
```

This creates:
- `dist/agentic-workflow-orchestrator-0.1.0.tar.gz` — source distribution
- `dist/agentic-workflow-orchestrator-0.1.0-py3-none-any.whl` — wheel (binary)

---

## Step 4: Verify Distribution

```bash
# Check what would be included
tar -tzf dist/agentic-workflow-orchestrator-0.1.0.tar.gz | head -20

# Check wheel contents
unzip -l dist/agentic-workflow-orchestrator-0.1.0-py3-none-any.whl | head -20

# Validate with twine
python -m twine check dist/*
```

Expected output: `PASSED` for both files.

---

## Step 5: Test Upload (TestPyPI)

Before uploading to the real PyPI, test with TestPyPI:

```bash
# Create account at https://test.pypi.org/account/register/

# Create ~/.pypirc with:
[distutils]
index-servers =
    testpypi
    pypi

[testpypi]
repository = https://test.pypi.org/legacy/
username = __token__
password = pypi-AgEIcHlwaS5vcmc...  # your TestPyPI API token

[pypi]
repository = https://upload.pypi.org/legacy/
username = __token__
password = pypi-AgEIcHlwaS5vcmc...  # your PyPI API token

# Upload to TestPyPI
python -m twine upload --repository testpypi dist/*

# Test install from TestPyPI
pip install --index-url https://test.pypi.org/simple/ agentic-workflow-orchestrator==0.1.0
```

---

## Step 6: Upload to PyPI (Production)

```bash
# Upload to official PyPI
python -m twine upload dist/*

# You'll be prompted for username/password (use __token__ / your token)
# Or use .pypirc (see Step 5)
```

Expected output:
```
Uploading agentic-workflow-orchestrator-0.1.0-py3-none-any.whl
Uploading agentic-workflow-orchestrator-0.1.0.tar.gz
View at:
https://pypi.org/project/agentic-workflow-orchestrator/0.1.0/
```

---

## Step 7: Verify on PyPI

```bash
# Verify package appears on PyPI
curl https://pypi.org/pypi/agentic-workflow-orchestrator/0.1.0/json | jq .

# Test install
pip install agentic-workflow-orchestrator

# Verify import works
python -c "from orchestrator import Orchestrator, Registry, Workflow; print('✓ Success')"
```

---

## GitHub Actions CI/CD (Optional but Recommended)

Create `.github/workflows/publish.yml` for automatic PyPI publishing on release:

```yaml
name: Publish to PyPI

on:
  release:
    types: [published]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'
      - run: pip install build twine
      - run: python -m build sdk-python/
      - run: python -m twine upload sdk-python/dist/* -u __token__ -p ${{ secrets.PYPI_TOKEN }}
```

---

## Version Bump Workflow

For each release:

1. Update version in `pyproject.toml` and `setup.py`
2. Update `CHANGELOG.md` with release notes
3. Commit: `git commit -m "chore: bump version to 0.2.0"`
4. Tag: `git tag v0.2.0`
5. Push: `git push && git push --tags`
6. Create GitHub Release (triggers CI/CD)
7. Or manually: `python -m twine upload dist/*`

---

## Versioning Strategy

Use Semantic Versioning:

- **0.1.0** → Initial release
- **0.1.1** → Patch (bug fixes)
- **0.2.0** → Minor (new features, backward compatible)
- **1.0.0** → Major (breaking changes)

---

## Package Contents

What gets uploaded to PyPI:

```
agentic-workflow-orchestrator-0.1.0/
├── orchestrator/
│   ├── __init__.py
│   ├── engine.py
│   ├── registry.py
│   ├── llm.py
│   ├── report.py
│   ├── spec.py
│   ├── ratelimit.py
│   └── mcp_integration.py
├── README.md
├── LICENSE
├── CHANGELOG.md
└── setup.py / pyproject.toml
```

**NOT included** (excluded by MANIFEST.in):
- `tests/` — tests not shipped with package
- `examples/` — examples accessible via repo, not package
- `__pycache__`, `.pyc` files

---

## PyPI Metadata

Your package will appear at:
```
https://pypi.org/project/agentic-workflow-orchestrator/
```

With:
- **Description:** From README.md (first section)
- **License:** Apache License 2.0
- **Python:** 3.9+
- **Keywords:** orchestration, workflow, multi-agent, LLM, MCP
- **Dependencies:** None (optional: anthropic for LLM support)

---

## User Installation

After publishing, users can install with:

```bash
# Basic install (no LLM support)
pip install agentic-workflow-orchestrator

# With LLM support (Anthropic Claude)
pip install agentic-workflow-orchestrator[llm]

# Development tools
pip install agentic-workflow-orchestrator[dev]
```

---

## Troubleshooting

### "Invalid distribution"
```bash
python -m twine check dist/*
```

### "Upload rejected: already exists"
- Version already published
- Bump version: `0.1.0` → `0.1.1`

### "File already uploaded"
- Delete from dist/: `rm dist/agentic-workflow-orchestrator-0.1.0*`
- Rebuild: `python -m build`

### "Forbidden: 403"
- Check PyPI token (Settings → API tokens)
- Ensure ~/.pypirc has correct token

---

## Commands Quick Reference

```bash
# Build
cd sdk-python && python -m build

# Test (TestPyPI)
python -m twine upload --repository testpypi dist/*

# Publish (PyPI)
python -m twine upload dist/*

# Install locally for testing
pip install -e .

# Check distribution
python -m twine check dist/*
```

---

## Next Steps

1. ✅ Complete steps 1–4 locally
2. ✅ Create PyPI account: https://pypi.org/account/register/
3. ✅ Generate API token in account settings
4. ✅ Run Step 6 (upload to PyPI)
5. ✅ Share package URL with users

**Your package will be live on PyPI within minutes!**

---

## Support

- PyPI Help: https://pypi.org/help/
- Twine Docs: https://twine.readthedocs.io/
- Setuptools: https://setuptools.pypa.io/
