---
name: verify-codebase
description: >-
  Use this skill when the user asks to verify the codebase, run pre-commit checks, or fix linting/architectural errors. It automates the process of running checks and iteratively fixing them until they all pass.
---

# Verify Codebase

This skill instructs the agent on how to thoroughly verify the `photoz` Django application codebase, run all pre-commit hooks, and recursively fix any issues that arise without bothering the user.

## Instructions

When invoked to verify the codebase or fix checks, you must follow this strict loop until all checks pass:

1. **Run Pre-commit Checks**:
   You must activate the virtual environment and run the full suite of pre-commit hooks from the `photoz` directory.
   Command to run:
   `cd photoz && source ./venv/bin/activate && pre-commit run --all-files`

2. **Analyze Failures**:
   If the command fails (exit code > 0), carefully read the output to identify which hooks failed (`ruff`, `pylint`, `import-linter`, `drift-check`, etc.).

3. **Iterative Fixing**:
   - **Ruff / Pylint**: Fix syntax, imports, or formatting issues in the specific files mentioned. Be careful to check if Django signals require `# pylint: disable=import-outside-toplevel`.
   - **Import-Linter**: If the "Independence of domain apps" contract is broken, determine if the import is an intentional boundary crossing (like wiring a cross-app signal). If it is intentional, update `photoz/.importlinter` to add the specific `module -> module` exception under `ignore_imports`. Otherwise, refactor the code to remove the dependency.
   - **Drift-Analyzer**: If architectural drift is flagged (e.g., `co_change_coupling`), analyze if the codebase was intentionally refactored. If the new architecture is functionally decoupled, update the drift baseline using: `cd photoz && source ./venv/bin/activate && drift-analyzer analyze --save-baseline .drift-baseline.json`. **Never scatter `# drift:ignore` comments.**

4. **Repeat**:
   After applying the fixes, you MUST repeat Step 1 (`pre-commit run --all-files`). Do not stop or ask the user for permission between fixes. Continue this loop of testing and fixing until the command exits with code `0` and all hooks explicitly pass.

5. **Completion**:
   Once all checks pass, stop and inform the user that the codebase is fully verified and perfectly clean.
