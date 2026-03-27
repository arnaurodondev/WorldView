from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

SRC_ROOT = Path(
    "/Users/arnaurodon/Projects/University/Final Thesis/eodhd-claude-skills/skills/eodhd-api/references/endpoints"
)
OUT_FILE = Path(
    "/Users/arnaurodon/Projects/University/Final Thesis/worldview/docs/" "references/eodhd-endpoints-reference.md"
)


def _extract_section(lines: list[str], name: str) -> str:
    pattern = re.compile(rf"^##\s+{re.escape(name)}\s*$", re.IGNORECASE)
    start: int | None = None
    for idx, line in enumerate(lines):
        if pattern.match(line.strip()):
            start = idx + 1
            break
    if start is None:
        return ""

    end = len(lines)
    for idx in range(start, len(lines)):
        if lines[idx].startswith("## "):
            end = idx
            break
    return "\n".join(lines[start:end]).strip("\n")


def generate() -> None:
    files = sorted(p for p in SRC_ROOT.glob("*.md") if p.name.lower() != "readme.md")

    header: list[str] = [
        "# EODHD Endpoints Canonical Reference",
        "",
        f"- Generated from eodhd-claude-skills endpoint docs on {datetime.now(tz=UTC).date().isoformat()}.",
        f"- Source folder: {SRC_ROOT}",
        f"- Endpoint count: {len(files)}",
        "- Scope: endpoint purpose, inputs (parameters), and outputs (response shapes), plus method/auth/URL metadata.",
        "- Usage: reference this file from execution prompts and implementation notes "
        "when endpoint contract details are needed.",
        "",
        "## Index",
        "",
        "| Endpoint | Slug | Source file |",
        "|---|---|---|",
    ]

    sections: list[str] = []
    metadata_re = re.compile(r"^([A-Za-z][A-Za-z \-/()]+):\s*(.+?)\s*$")

    for path in files:
        text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n")
        lines = text.split("\n")

        if lines and lines[0].startswith("#"):
            title = lines[0].strip().lstrip("#").strip()
        else:
            title = path.stem.replace("-", " ").title()

        metadata: dict[str, str] = {}
        i = 1
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith("## "):
                break
            match = metadata_re.match(line)
            if match:
                metadata[match.group(1).strip()] = match.group(2).strip()
            i += 1

        slug = path.stem
        header.append(f"| [{title}](#{slug}) | {slug} | `{path}` |")

        purpose = _extract_section(lines, "Purpose")
        params = _extract_section(lines, "Parameters")
        response = _extract_section(lines, "Response (shape)")
        examples = _extract_section(lines, "Example Requests") or _extract_section(lines, "Example request")
        notes = _extract_section(lines, "Notes")
        statuses = _extract_section(lines, "HTTP Status Codes")

        section: list[str] = [
            "",
            f"## {title}",
            "",
            f'<a id="{slug}"></a>',
            "",
            "### Endpoint Metadata",
            "",
            "| Field | Value |",
            "|---|---|",
        ]

        for key in ["Status", "Source", "Docs", "Provider", "Base URL", "Path", "Method", "Auth"]:
            if key in metadata:
                section.append(f"| {key} | {metadata[key]} |")
        section.append(f"| Slug | `{slug}` |")
        section.append(f"| Source File | `{path}` |")

        if purpose:
            section.extend(["", "### Purpose", "", purpose])
        if params:
            section.extend(["", "### Inputs", "", params])
        if response:
            section.extend(["", "### Outputs", "", response])
        if examples:
            section.extend(["", "### Example Requests", "", examples])
        if notes:
            section.extend(["", "### Notes", "", notes])
        if statuses:
            section.extend(["", "### HTTP Status Codes", "", statuses])

        sections.append("\n".join(section).rstrip())

    content = "\n".join(header).rstrip() + "\n\n---\n" + "\n\n---\n".join(sections) + "\n"
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(content, encoding="utf-8")
    print(f"Wrote {OUT_FILE} with {len(files)} endpoints")


if __name__ == "__main__":
    generate()
