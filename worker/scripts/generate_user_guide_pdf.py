"""Compile les chapitres docs/user-guide/*.md en un PDF imprimable.

Sortie : docs/user-guide.pdf

Usage :
  python worker/scripts/generate_user_guide_pdf.py
  python worker/scripts/generate_user_guide_pdf.py --output other/path.pdf
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "worker" / "src"))

USER_GUIDE_DIR = REPO_ROOT / "docs" / "user-guide"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "user-guide.pdf"


PRINT_CSS = """
@page {
    size: A4 portrait;
    margin: 2cm 1.8cm 2.4cm 1.8cm;
    @bottom-left {
        content: "Employé IA Fiduciaire — Manuel utilisateur";
        font-size: 8pt; color: #777;
    }
    @bottom-right {
        content: "Page " counter(page) " / " counter(pages);
        font-size: 8pt; color: #777;
    }
}
@page :first { @bottom-left { content: ""; } @bottom-right { content: ""; } }

html { font-family: 'Inter', 'Helvetica', system-ui, sans-serif; }
body { color: #111; font-size: 10.5pt; line-height: 1.55; }

h1 {
    font-size: 22pt; color: #111; margin-top: 0; margin-bottom: 14pt;
    page-break-before: always;
}
h1:first-of-type { page-break-before: avoid; }
h2 {
    font-size: 14pt; color: #222; margin-top: 18pt; margin-bottom: 6pt;
    border-bottom: 1px solid #ccc; padding-bottom: 2pt;
}
h3 {
    font-size: 11pt; color: #333; margin-top: 12pt; margin-bottom: 4pt;
    font-weight: 600;
}

p { margin: 5pt 0; text-align: justify; }
ul, ol { padding-left: 18pt; }
li { margin: 2pt 0; }

table { border-collapse: collapse; width: 100%; margin: 10pt 0; }
th, td { border: 1px solid #999; padding: 4px 6px; font-size: 10pt;
         vertical-align: top; text-align: left; }
th { background: #f0f0f0; font-weight: 600; }

pre, code {
    font-family: 'SF Mono', 'Menlo', 'Monaco', monospace;
    background: #f4f4f4;
    border: 1px solid #ddd;
}
code { padding: 0 3px; font-size: 9.5pt; border-radius: 2px; }
pre {
    padding: 8pt; border-radius: 3px; font-size: 9pt;
    page-break-inside: avoid;
    white-space: pre-wrap; word-wrap: break-word;
    overflow-wrap: anywhere;
}
pre code { background: none; border: none; padding: 0; }

strong { color: #111; }
em { color: #444; }

div.cover {
    page-break-after: always;
    padding-top: 4cm;
    text-align: center;
}
div.cover h1 {
    font-size: 32pt; border: none; margin-bottom: 20pt;
    page-break-before: avoid;
}
div.cover .subtitle { font-size: 14pt; color: #555; margin-bottom: 40pt; }
div.cover .meta { font-size: 10pt; color: #888; margin-top: 60pt; }

nav.toc {
    page-break-after: always;
}
nav.toc h2 { margin-top: 0; }
nav.toc ol { list-style: decimal; padding-left: 20pt; }
nav.toc li { margin: 6pt 0; font-size: 11pt; }
"""


def _load_chapters() -> list[tuple[str, str]]:
    """Retourne [(filename, md_text)] triés par numéro."""
    files = sorted(USER_GUIDE_DIR.glob("*.md"))
    return [(f.name, f.read_text(encoding="utf-8")) for f in files]


def _extract_title(md: str, fallback: str) -> str:
    """Première ligne `# Titre` (ATX heading)."""
    for line in md.splitlines():
        line = line.strip()
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip()
    return fallback


def _md_to_html_body(md_text: str) -> str:
    import markdown
    return markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "sane_lists", "nl2br"],
        output_format="html5",
    )


def build_user_guide_pdf(output: Path = DEFAULT_OUTPUT) -> Path:
    """Compile les chapitres en 1 PDF. Retourne le chemin du PDF."""
    try:
        import weasyprint
    except ImportError as exc:
        raise RuntimeError(
            "weasyprint non installé. Installer via : pip install weasyprint",
        ) from exc

    chapters = _load_chapters()
    if not chapters:
        raise RuntimeError(
            f"Aucun fichier .md trouvé dans {USER_GUIDE_DIR}",
        )

    today = datetime.now().strftime("%Y-%m-%d")
    cover_html = f"""
<div class="cover">
  <h1>Employé IA Fiduciaire</h1>
  <div class="subtitle">Manuel utilisateur — édition cabinet pilote</div>
  <div class="meta">
    Version {today} · LX Studio · Tanguy Lachat<br>
    contact@lxstudio.ch
  </div>
</div>
"""

    toc_items: list[str] = []
    chapter_html_parts: list[str] = []
    for filename, md in chapters:
        title = _extract_title(md, filename)
        toc_items.append(f"<li>{title}</li>")
        chapter_html_parts.append(_md_to_html_body(md))

    toc_html = (
        "<nav class=\"toc\"><h2>Table des matières</h2><ol>"
        + "\n".join(toc_items)
        + "</ol></nav>"
    )

    body = cover_html + toc_html + "\n".join(chapter_html_parts)
    html = f"""<!doctype html>
<html lang="fr-CH">
<head>
<meta charset="utf-8">
<title>Employé IA Fiduciaire — Manuel utilisateur</title>
<style>{PRINT_CSS}</style>
</head>
<body>
{body}
</body>
</html>
"""

    output.parent.mkdir(parents=True, exist_ok=True)
    weasyprint.HTML(
        string=html, base_url=str(USER_GUIDE_DIR),
    ).write_pdf(output)
    return output


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compile docs/user-guide/*.md en docs/user-guide.pdf",
    )
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Chemin PDF cible (défaut : {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    print(f"Compilation user-guide → PDF")
    print(f"  source : {USER_GUIDE_DIR}")
    print(f"  cible  : {args.output}")
    print()

    try:
        out = build_user_guide_pdf(args.output)
    except RuntimeError as exc:
        print(f"✗ {exc}", file=sys.stderr)
        return 1

    size_kb = out.stat().st_size / 1024
    print(f"✅ PDF généré : {out} ({size_kb:.1f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
