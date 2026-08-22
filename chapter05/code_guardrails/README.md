# Code and Architecture Guardrails

* linting and formatting setup for the `photoz` application.
* architecture guardrails to avoid drift of photoz architecture.

## Tools

| Tool | Purpose |
|------|---------|
| [ruff](https://docs.astral.sh/ruff/) | Formatting + fast lint (replaces flake8, isort, pyupgrade) |
| [pylint](https://pylint.readthedocs.io/) | Deep static analysis (complexity, class design, Django checks) |
| [pre-commit](https://pre-commit.com/) | Runs both tools automatically on every `git commit` |

Pylint rule set is reduced — rules already enforced by ruff are disabled to avoid duplicate reporting. Config lives in [`photoz/pyproject.toml`](../../photoz/pyproject.toml).

## Why Both?

Ruff is fast but shallow — it catches formatting and obvious errors. Pylint is slower but catches things ruff cannot: high cyclomatic complexity, too many arguments, class design issues, and Django-specific false positives via `pylint-django`.

## How It Works

```
git commit
    └── pre-commit hook fires
            ├── ruff check --fix   (auto-fixes safe issues, blocks on errors)
            ├── ruff format        (enforces formatting)
            └── pylint             (reports errors, blocks commit if found)
```

On GitHub, a `lint` job runs on every push to `main` and `staging`. The `test` job only runs if `lint` passes — so a lint failure blocks the full deploy pipeline.

```
push to main/staging
    └── lint job (ruff + pylint)
            └── [passes] test job
                    └── [passes] migrate + deploy
```

## Setup and Commands

See [`photoz/README.md — Code Quality`](../../photoz/README.md#code-quality) for:
- Installing the pre-commit hook
- Running ruff and pylint manually
- The same runs are also happen as part of GitHub actions
