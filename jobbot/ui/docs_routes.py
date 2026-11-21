"""Documentation indexing and safe Markdown retrieval for the dashboard."""

import re

from .. import paths

DOCS = paths.REPO / "docs"


def docs_index():
    """Pages in docs/, in the order the docs index lists them."""
    order = re.findall(r"\]\(([\w-]+)\.md\)", (DOCS / "README.md").read_text(encoding="utf-8")) if (DOCS / "README.md").exists() else []
    names = order + sorted(p.stem for p in DOCS.glob("*.md") if p.stem not in order and p.stem != "README")
    pages = []
    for name in ["README"] + names:
        f = DOCS / f"{name}.md"
        if f.exists():
            title = re.search(r"^# (.+)$", f.read_text(encoding="utf-8"), re.M)
            text = title.group(1).replace("`", "") if title else name
            pages.append({"name": name, "title": "Overview" if name == "README" else text})
    return pages


def doc_page(name):
    """One docs page's Markdown. Only plain names of files directly in docs/ (no paths)."""
    if not re.fullmatch(r"[\w-]{1,40}", name or ""):
        return None
    f = (DOCS / f"{name}.md").resolve()
    if f.parent != DOCS.resolve() or not f.is_file():
        return None
    return {"name": name, "text": f.read_text(encoding="utf-8")}

