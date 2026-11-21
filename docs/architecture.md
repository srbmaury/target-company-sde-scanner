# Architecture and code-quality audit

The audit is intentionally incremental: preserve stable CLI, scanner, and dashboard interfaces while reducing coupling.

## Automated checks

Run `python scripts/architecture_audit.py --check` to enforce source-file ceilings, Python syntax, and duplicate definitions in the same scope. The CI workflow also runs `pyflakes`, the unit/browser suite, coverage reporting, and `pip-audit`. Existing large files have explicit ceilings; those are **temporary debt budgets**, not preferred file sizes. Reduce ceilings when modules shrink.

## Findings and recommended boundaries

| File | Finding | Refactor boundary |
| --- | --- | --- |
| `jobbot/apply/engine.py` | Session manages navigation, form filling, review, and submission | Extracted `apply/text_length.py`; remaining browser orchestration needs browser-level coverage |
| `jobbot/ui/server.py` | HTTP transport, account management, profile editing, tasks, and tracking routes coexist | Extracted `ui/docs_routes.py`; remaining request validation, account/profile services, and route dispatch |
| `jobbot/ui/static/app.js` | Networking, state, rendering, and interaction logic share a large global module | Extracted `static/html_utils.js`; remaining API client and independent views must retain CSP compatibility |
| `jobbot/answers.py` | Rule matching, model fallback, caching, and prompting in one resolver | Extracted `answer_options.py`; remaining rule predicates and model integration |
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
