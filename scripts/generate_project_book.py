from __future__ import annotations

import ast
import html
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.tableofcontents import TableOfContents


ROOT = Path(__file__).resolve().parents[1]
DOCS_DIR = ROOT / "docs"
MARKDOWN_OUT = DOCS_DIR / "PROJECT_BOOK.md"
PDF_OUT = DOCS_DIR / "PROJECT_BOOK.pdf"

IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
    "uploads",
    "tinious",
    "photo\\_doc_extract",
    "docs",
}

TEXT_EXTENSIONS = {
    ".py",
    ".md",
    ".txt",
    ".json",
    ".yml",
    ".yaml",
    ".ini",
    ".cfg",
    ".toml",
    ".html",
    ".css",
    ".js",
    ".bat",
    ".sql",
    ".csv",
    ".mako",
    ".env",
}


def normalize_dir_name(p: Path) -> str:
    return str(p).replace("/", "\\").lower()


def should_skip_dir(path: Path) -> bool:
    norm = normalize_dir_name(path)
    for ignored in IGNORE_DIRS:
        if ignored.lower() in norm:
            return True
    return False


def is_probably_text_file(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    try:
        chunk = path.read_bytes()[:4096]
    except OSError:
        return False
    return b"\x00" not in chunk


def iter_project_files(root: Path) -> Iterable[Path]:
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if should_skip_dir(rel.parent):
            continue
        if p.name in {"PROJECT_BOOK.md", "PROJECT_BOOK.pdf"}:
            continue
        if not is_probably_text_file(p):
            continue
        yield p


def read_text_file(path: Path) -> list[str]:
    for encoding in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return path.read_text(encoding=encoding).splitlines()
        except UnicodeDecodeError:
            continue
    return ["<unreadable text file>"]


def infer_file_topics(path: Path, lines: list[str]) -> list[str]:
    content = "\n".join(lines).lower()
    topics = []
    if path.suffix == ".py":
        topics.append("python")
    if "flask" in content:
        topics.append("flask web routing")
    if "sqlalchemy" in content:
        topics.append("database orm")
    if "alembic" in content or "migration" in content:
        topics.append("database migrations")
    if "jinja" in content or "{{" in content:
        topics.append("templating")
    if path.suffix == ".html":
        topics.append("frontend markup")
    if path.suffix == ".css":
        topics.append("styling")
    if "pytest" in content or "def test_" in content:
        topics.append("testing")
    if path.suffix in {".yml", ".yaml", ".ini", ".cfg", ".toml", ".env"}:
        topics.append("configuration")
    if path.name.lower().startswith("docker") or "docker" in content:
        topics.append("containerization")
    if "csrf" in content or "auth" in path.parts:
        topics.append("security/authentication")
    return sorted(set(topics))


def extract_python_imports(source: str) -> list[str]:
    imports: list[str] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return imports
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                imports.append(name.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module.split(".")[0])
    return sorted(set(imports))


def explain_line(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return "Blank line used for readability and logical separation."
    if stripped.startswith("#"):
        return "Comment line documenting intent or context for nearby code."
    if stripped.startswith('"""') or stripped.startswith("'''"):
        return "Docstring boundary used to describe a module, class, or function."
    if stripped.startswith("import "):
        modules = stripped.replace("import", "", 1).strip()
        return f"Imports dependency modules: {modules}."
    if stripped.startswith("from "):
        return "Imports specific names from another module for direct usage."
    if stripped.startswith("@"):
        return "Decorator line that modifies the behavior of the definition below."
    if re.match(r"^class\s+\w+", stripped):
        return "Declares a class that groups related state and behavior."
    if re.match(r"^def\s+\w+", stripped) or re.match(r"^async\s+def\s+\w+", stripped):
        return "Declares a function/method as a reusable unit of behavior."
    if stripped.startswith(("if ", "elif ")):
        return "Conditional branch that runs only when its condition is true."
    if stripped == "else:":
        return "Fallback branch executed when prior conditions are false."
    if stripped.startswith("for "):
        return "Loop iterating over a sequence to process elements one by one."
    if stripped.startswith("while "):
        return "Loop that repeats while its condition remains true."
    if stripped.startswith("try:"):
        return "Starts an exception handling block for risky operations."
    if stripped.startswith("except"):
        return "Handles errors raised in the associated try block."
    if stripped.startswith("finally:"):
        return "Runs cleanup logic regardless of success or failure."
    if stripped.startswith("with "):
        return "Context manager block for safe setup and automatic cleanup."
    if stripped.startswith("return"):
        return "Returns a value (or control) back to the caller."
    if stripped.startswith("raise "):
        return "Raises an explicit exception to signal an error condition."
    if stripped in {"pass", "continue", "break"}:
        return "Flow-control keyword affecting execution in the current block."
    if "=" in stripped and not any(op in stripped for op in ["==", "!=", ">=", "<="]):
        return "Assignment statement storing or updating program state."
    if stripped.startswith("<") and stripped.endswith(">"):
        return "Markup line defining structure in an HTML-like template file."
    if stripped.startswith(".") or stripped.startswith("#"):
        return "CSS selector line choosing the elements styled below."
    if stripped.endswith("{") or stripped.endswith("}"):
        return "Block delimiter controlling scope/structure in this language."
    return "Operational statement participating in the file's runtime behavior."


def build_file_record(path: Path) -> dict:
    rel = path.relative_to(ROOT)
    lines = read_text_file(path)
    text = "\n".join(lines)
    topics = infer_file_topics(rel, lines)

    imports: list[str] = []
    if rel.suffix == ".py":
        imports = extract_python_imports(text)

    line_entries = []
    for idx, line in enumerate(lines, start=1):
        code = line.replace("|", "\\|")
        explanation = explain_line(line).replace("|", "\\|")
        line_entries.append((idx, code, explanation))

    return {
        "path": str(rel).replace("\\", "/"),
        "line_count": len(lines),
        "topics": topics,
        "imports": imports,
        "line_entries": line_entries,
    }


def summarize_architecture(records: list[dict]) -> dict:
    by_top_folder = Counter()
    all_topics = Counter()
    all_imports = Counter()

    for rec in records:
        path = rec["path"]
        top = path.split("/")[0] if "/" in path else "root"
        by_top_folder[top] += 1
        for t in rec["topics"]:
            all_topics[t] += 1
        for imp in rec["imports"]:
            all_imports[imp] += 1

    return {
        "folders": by_top_folder,
        "topics": all_topics,
        "imports": all_imports,
    }


def write_markdown(records: list[dict], architecture: dict) -> None:
    lines: list[str] = []
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    lines.append("# Project Master Book")
    lines.append("")
    lines.append(f"Generated: {generated}")
    lines.append("")
    lines.append("## Table of Contents")
    lines.append("")
    lines.append("1. Project Scope and Goals")
    lines.append("2. Architecture and System Design")
    lines.append("3. Libraries and Framework Usage")
    lines.append("4. File-by-File Deep Explanation")
    lines.append("5. Line-by-Line Explanation for Every Included File")
    lines.append("")

    lines.append("## 1. Project Scope and Goals")
    lines.append("")
    lines.append(
        "This book explains the project in a strict sequence: high-level goals, architecture, libraries, "
        "then every file with line-by-line detail."
    )
    lines.append(f"Total included text files: {len(records)}")
    lines.append("")

    lines.append("## 2. Architecture and System Design")
    lines.append("")
    lines.append("### Folder Distribution")
    for folder, count in architecture["folders"].most_common():
        lines.append(f"- {folder}: {count} files")
    lines.append("")

    lines.append("### Topic Distribution")
    for topic, count in architecture["topics"].most_common():
        lines.append(f"- {topic}: {count} files")
    lines.append("")

    lines.append("## 3. Libraries and Framework Usage")
    lines.append("")
    lines.append("### Python Imports Observed")
    for lib, count in architecture["imports"].most_common():
        lines.append(f"- {lib}: referenced in {count} Python files")
    lines.append("")

    lines.append("## 4. File-by-File Deep Explanation")
    lines.append("")
    for idx, rec in enumerate(records, start=1):
        lines.append(f"### File {idx}: {rec['path']}")
        lines.append(f"- Line count: {rec['line_count']}")
        lines.append(
            "- Topics: " + (", ".join(rec["topics"]) if rec["topics"] else "general project support")
        )
        lines.append(
            "- Key libraries: " + (", ".join(rec["imports"]) if rec["imports"] else "not applicable")
        )
        lines.append("")

    lines.append("## 5. Line-by-Line Explanation for Every Included File")
    lines.append("")

    for idx, rec in enumerate(records, start=1):
        lines.append(f"### File {idx}: {rec['path']}")
        lines.append("")
        lines.append("| Line | Code | Explanation |")
        lines.append("|---:|---|---|")
        for line_no, code, explanation in rec["line_entries"]:
            safe_code = code if len(code) <= 240 else f"{code[:237]}..."
            lines.append(f"| {line_no} | {safe_code} | {explanation} |")
        lines.append("")

    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    MARKDOWN_OUT.write_text("\n".join(lines), encoding="utf-8")


class BookTemplate(SimpleDocTemplate):
    def afterFlowable(self, flowable):
        if isinstance(flowable, Paragraph):
            style_name = flowable.style.name
            if style_name in {"Heading1", "Heading2", "Heading3"}:
                level = {"Heading1": 0, "Heading2": 1, "Heading3": 2}[style_name]
                text = flowable.getPlainText()
                self.notify("TOCEntry", (level, text, self.page))


def write_pdf(records: list[dict], architecture: dict) -> None:
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()

    code_style = ParagraphStyle(
        "CodeLine",
        parent=styles["BodyText"],
        fontName="Courier",
        fontSize=6.7,
        leading=8,
    )

    body_style = ParagraphStyle(
        "DenseBody",
        parent=styles["BodyText"],
        fontSize=9,
        leading=11,
    )

    toc = TableOfContents()
    toc.levelStyles = [
        ParagraphStyle(fontSize=10, name="TOCLevel1", leftIndent=20, firstLineIndent=-12, spaceBefore=4),
        ParagraphStyle(fontSize=9, name="TOCLevel2", leftIndent=36, firstLineIndent=-12, spaceBefore=2),
        ParagraphStyle(fontSize=8, name="TOCLevel3", leftIndent=52, firstLineIndent=-12, spaceBefore=1),
    ]

    story = []
    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    story.append(Paragraph("Project Master Book", styles["Title"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Generated: {generated}", body_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Table of Contents", styles["Heading1"]))
    story.append(toc)
    story.append(PageBreak())

    story.append(Paragraph("1. Project Scope and Goals", styles["Heading1"]))
    story.append(
        Paragraph(
            "This documentation explains the complete project in a strict sequence: "
            "scope, architecture, libraries, file deep-dives, then line-level explanations.",
            body_style,
        )
    )
    story.append(Paragraph(f"Included files: {len(records)}", body_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph("2. Architecture and System Design", styles["Heading1"]))
    story.append(Paragraph("Folder Distribution", styles["Heading2"]))
    folder_table_data = [["Folder", "File Count"]]
    for folder, count in architecture["folders"].most_common():
        folder_table_data.append([folder, str(count)])
    folder_table = Table(folder_table_data, colWidths=[260, 100])
    folder_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(folder_table)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Topic Distribution", styles["Heading2"]))
    topic_table_data = [["Topic", "Files"]]
    for topic, count in architecture["topics"].most_common():
        topic_table_data.append([topic, str(count)])
    topic_table = Table(topic_table_data, colWidths=[260, 100])
    topic_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(topic_table)
    story.append(PageBreak())

    story.append(Paragraph("3. Libraries and Framework Usage", styles["Heading1"]))
    imports_table_data = [["Library", "Python Files Referencing"]]
    for lib, count in architecture["imports"].most_common():
        imports_table_data.append([lib, str(count)])
    imports_table = Table(imports_table_data, colWidths=[260, 100])
    imports_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(imports_table)
    story.append(PageBreak())

    story.append(Paragraph("4. File-by-File Deep Explanation", styles["Heading1"]))
    for idx, rec in enumerate(records, start=1):
        story.append(Paragraph(f"File {idx}: {html.escape(rec['path'])}", styles["Heading2"]))
        story.append(Paragraph(f"Line count: {rec['line_count']}", body_style))
        topics = ", ".join(rec["topics"]) if rec["topics"] else "general project support"
        imports = ", ".join(rec["imports"]) if rec["imports"] else "not applicable"
        story.append(Paragraph(f"Topics: {html.escape(topics)}", body_style))
        story.append(Paragraph(f"Key libraries: {html.escape(imports)}", body_style))
        story.append(Spacer(1, 5))

    story.append(PageBreak())
    story.append(Paragraph("5. Line-by-Line Explanation for Every Included File", styles["Heading1"]))

    for idx, rec in enumerate(records, start=1):
        story.append(PageBreak())
        story.append(Paragraph(f"File {idx}: {html.escape(rec['path'])}", styles["Heading2"]))
        story.append(Spacer(1, 4))
        for line_no, code, explanation in rec["line_entries"]:
            safe_code = code if len(code) <= 180 else f"{code[:177]}..."
            item = f"L{line_no:04d} | {safe_code} | {explanation}"
            story.append(Preformatted(item, code_style))

    doc = BookTemplate(str(PDF_OUT), pagesize=A4, leftMargin=32, rightMargin=32, topMargin=28, bottomMargin=28)
    doc.multiBuild(story)


def main() -> None:
    files = [build_file_record(path) for path in iter_project_files(ROOT)]
    architecture = summarize_architecture(files)
    write_markdown(files, architecture)
    write_pdf(files, architecture)
    print(f"Generated: {MARKDOWN_OUT}")
    print(f"Generated: {PDF_OUT}")
    print(f"Included files: {len(files)}")


if __name__ == "__main__":
    main()
