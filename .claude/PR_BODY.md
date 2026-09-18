## Description
The repo had no custom CI — only GitHub's own "Codespaces Prebuilds" workflow, which prebuilds a devcontainer image on every push and has nothing to do with code correctness (it doesn't run tests, doesn't gate PRs). This adds a real GitHub Actions workflow that runs the Django test suite on every PR and every push to `main`.

## Changes
- `.github/workflows/tests.yml`: new workflow — Python 3.10 (matches the local `venv`), `pip install -r requirements.txt`, `manage.py makemigrations --check --dry-run`, then `manage.py test`. Uses `DB_ENGINE=sqlite` and dummy values for the other required settings (`SECRET_KEY`, email, Celery) supplied as workflow `env:` vars — no `.env` file or secrets needed since none of those services are actually exercised by the test suite.

## How to test
1. Verified locally by exporting the exact same env vars the workflow sets and running `manage.py makemigrations --check --dry-run` + `manage.py test` — both pass (55/55 tests)
2. Once this PR is open, its own GitHub Actions run is the real end-to-end proof

## Issue
None — ad hoc infra request.
