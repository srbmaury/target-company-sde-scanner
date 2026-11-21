"""Architecture health report and guardrails for production source files.

Run: python scripts/architecture_audit.py
     python scripts/architecture_audit.py --check

The baseline is intentionally a *ceiling*, not a target. Existing large modules
are reported but cannot grow without a conscious baseline review.
"""
import argparse
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "jobbot"
EXTENSIONS = {".py", ".js", ".css", ".html"}
# Legacy modules: reduce these ceilings as responsibilities are extracted.
MAX_LINES = {
    "jobbot/ui/static/app.js": 1850,
    "jobbot/apply/engine.py": 1150,
    "jobbot/answers.py": 925,
    "jobbot/ui/server.py": 925,
    "jobbot/scan.py": 825,
    "jobbot/cli.py": 675,
}
DEFAULT_MAX_LINES = 600


def duplicate_definitions(tree):
    """Detect overwritten functions/methods in a single Python scope."""
    problems = []

    def visit(node, scope):
        if not isinstance(node, (ast.Module, ast.ClassDef)):
            return
        names = set()
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if item.name in names:
                    problems.append(f"{scope}.{item.name} (line {item.lineno})")
                names.add(item.name)
                if isinstance(item, ast.ClassDef):
                    visit(item, f"{scope}.{item.name}")

    visit(tree, "module")
    return problems


def audit():
    rows, violations = [], []
    for path in sorted(SOURCE.rglob("*")):
        if not path.is_file() or path.suffix not in EXTENSIONS:
            continue
        rel = path.relative_to(ROOT).as_posix()
        lines = path.read_text(encoding="utf-8").splitlines()
        limit = MAX_LINES.get(rel, DEFAULT_MAX_LINES)
        rows.append((rel, len(lines), limit))
        if len(lines) > limit:
            violations.append(f"{rel}: {len(lines)} lines exceeds {limit}-line ceiling")
        if path.suffix == ".py":
            try:
                tree = ast.parse("\n".join(lines), filename=rel)
            except SyntaxError as exc:
                violations.append(f"{rel}: syntax error at line {exc.lineno}: {exc.msg}")
                continue
            for name in duplicate_definitions(tree):
                violations.append(f"{rel}: duplicate definition {name}")
    return rows, violations


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if guardrails are violated")
    args = parser.parse_args()
    rows, violations = audit()
    for path, lines, limit in sorted(rows, key=lambda row: -row[1]):
        print(f"{lines:5d} / {limit:5d}  {path}")
    print(f"\nAudited {len(rows)} source files; {len(violations)} guardrail violations.")
    for issue in violations:
        print(f"  ERROR: {issue}")
    return int(bool(args.check and violations))


if __name__ == "__main__":
    raise SystemExit(main())
