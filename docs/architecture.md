# Architecture and code-quality audit

The audit is intentionally incremental: preserve stable CLI, scanner, and dashboard interfaces while reducing coupling.

## Automated checks

Run `python scripts/architecture_audit.py --check` to enforce source-file ceilings, Python syntax, and duplicate definitions in the same scope. The CI workflow also runs `pyflakes`, the unit/browser suite, coverage reporting, and `pip-audit`. Existing large files have explicit ceilings; those are **temporary debt budgets**, not preferred file sizes. Reduce ceilings when modules shrink.

## Findings and recommended boundaries

| File | Finding | Refactor boundary |
| --- | --- | --- |
| `jobbot/apply/engine.py` | Session manages navigation, form filling, review, and submission | Extracted `apply/text_length.py`; remaining browser orchestration needs browser-level coverage |
| `jobbot/ui/server.py` | HTTP transport, account management, profile editing, tasks, and tracking routes coexist | Extracted `ui/docs_routes.py`, `ui/job_views.py`, and `ui/summary.py`; remaining request validation, account/profile services, and route dispatch |
| `jobbot/ui/static/app.js` | Networking, state, rendering, and interaction logic share a large global module | Extracted `static/html_utils.js` and `static/network.js`; independent views still need splitting while retaining CSP compatibility |
| `jobbot/answers.py` | Rule matching, model fallback, caching, and prompting in one resolver | Extracted `answer_options.py` including experience-bucket matching; remaining rule predicates and model integration |
| `jobbot/scan.py` | ATS adapters, filtering, experience extraction, and CLI orchestration | Extracted `scan_experience.py`; later group adapters by provider |
| `jobbot/cli.py` | Parser registration and command execution mixed | Split commands by domain without changing public commands |
| `jobbot/tracker.py` | SQLite operations and hosted persistence in same module | Separate storage adapter only after concurrency/CAS tests |

## SOLID and separation-of-concerns rules

1. **SRP:** keep parsing and scoring pure; move transport, storage, and UI out of business logic when practical.
2. **OCP:** new ATS providers should register an adapter instead of changing unrelated scanners.
3. **LSP/ISP:** introduce protocols only where multiple real implementations need the same contract; avoid speculative abstraction.
4. **DIP:** ranking should depend on experience parsing, not import the full scanner (addressed by `scan_experience.py`).
5. **Naming:** snake_case Python modules/functions, PascalCase classes, uppercase constants, and domain-oriented names.
6. **Dead code:** use references and tests before deleting; broad exception handlers require a documented failure boundary.
7. **Compatibility:** preserve public imports until callers and tests migrate; refactor in reviewable commits.

## Follow-up validation

Run full Python matrix and Playwright tests after each extraction. Hosted OAuth, browser isolation, and credential redaction require separate runtime/security validation; static inspection cannot certify them. Avoid a single sweeping folder rename or deletion pass.

## Dead-code review

The Python CI linter catches unused imports and undefined names. During these extractions, unused compatibility imports were removed rather than suppressing warnings. No functions were deleted based solely on a heuristic: reflective references, tests, and externally imported helpers can make apparently unused symbols part of the public API. Additional dead-code removal requires call-site analysis and tests.

## Readability and naming inventory

The audit now emits **non-blocking** findings for functions longer than 100 lines and unconventional Python function names. These are review prompts rather than automatic defects: public API naming, overrides, generated code, and framework hooks can justify exceptions. Duplicate definitions and file-size ceilings remain blocking. Reassess the long-function threshold after reducing legacy modules; do not split a cohesive algorithm merely to satisfy a metric.

## Regression found during extraction

The first frontend helper extraction placed top-level `const` bindings in two classic scripts, preventing dashboard initialization. The helper is now wrapped in an IIFE so only the explicit `window.JobbotHtml` API is exported. A browser regression test verifies startup, HTML escaping, and rejection of `javascript:` links. An architecture test also had an incorrectly escaped newline and has been corrected. These illustrate why browser coverage is required for module boundaries.

## CI validation milestone

Commit `36fe382` passed the configured Python matrix after fixing the extracted HTML helper's global scope and the architecture test. A subsequent extraction moves dashboard API transport and connection status into `static/network.js`; it has a Chromium startup assertion and must pass the full matrix before merging. The remaining large view renderers and browser automation workflow are intentionally not mechanically split without integration coverage.

## CLI boundary

`cli_format.py` now contains pure job-range expansion and display truncation. The CLI retains its existing public helper names for compatibility. The larger `build_parser` command registration remains in `cli.py` pending a command-registry design and focused parser integration tests; splitting it without that coverage would add indirection without a proven readability benefit.

## Documentation pruning

Only the root `README.md` and Markdown pages served by the dashboard (`docs/`) remain. The standalone assistant skill, company-tier reference, supplemental platform list, and contributing guide were intentionally removed at the user's request. The ATS registry remains the scanner's structured source configuration. The documentation viewer still indexes `docs/README.md` and the linked pages.
