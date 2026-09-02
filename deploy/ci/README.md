# CI pipeline — pending installation

`ci.yml` is the real pipeline: lint, security scan, tests, the production
migration path plus `alembic check`, frontend module parsing, and an image
build. **GitHub does not run it from this directory.**

It lives here rather than in `.github/workflows/` because pushing a workflow
file requires a token carrying the `workflow` scope, and the token in use does
not have it. GitHub rejects the entire push, not just that file.

To activate it:

```bash
gh auth refresh -s workflow          # approve in the browser
git mv deploy/ci/ci.yml .github/workflows/ci.yml
git commit -m "ci: install the pipeline where GitHub runs it"
git push
```

Until that happens nothing gates a push, so run the suite locally before
deploying:

```bash
DATABASE_URL=sqlite:///./t.db .venv/bin/python -m pytest tests/ -q
.venv/bin/python -m ruff check app/ --select E,F,I,W --ignore E501
```
