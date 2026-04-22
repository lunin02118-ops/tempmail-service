from pathlib import Path
from markdown import markdown

BASE = Path('/opt/hermes/mail-telegram-app')
OUT = BASE / 'Standalone-Mail-Telegram-App-Docs.pdf'
DOCS = [
    ('Architecture', BASE / 'ARCHITECTURE.md'),
    ('Bootstrap Plan', BASE / 'docs-plan.md'),
]

parts = []
for title, path in DOCS:
    text = path.read_text(encoding='utf-8')
    body = markdown(text, extensions=['fenced_code', 'tables', 'toc'])
    parts.append(f"<section class='doc'><h1>{title}</h1>{body}</section>")

html = f"""<!doctype html>
<html lang='ru'>
<head>
  <meta charset='utf-8'>
  <style>
    @page {{ size: A4; margin: 18mm 14mm 18mm 14mm; }}
    body {{ font-family: DejaVu Sans, sans-serif; color: #111; font-size: 11pt; line-height: 1.45; }}
    h1 {{ font-size: 22pt; margin: 0 0 10pt 0; border-bottom: 1px solid #ccc; padding-bottom: 6pt; }}
    h2 {{ font-size: 16pt; margin: 18pt 0 8pt; }}
    h3 {{ font-size: 13pt; margin: 14pt 0 6pt; }}
    p, li {{ margin: 0 0 6pt 0; }}
    pre {{ background: #f6f8fa; padding: 10pt; border-radius: 4pt; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 9pt; }}
    code {{ font-family: DejaVu Sans Mono, monospace; }}
    table {{ border-collapse: collapse; width: 100%; margin: 8pt 0 12pt; font-size: 10pt; }}
    th, td {{ border: 1px solid #d0d7de; padding: 6pt 8pt; vertical-align: top; }}
    th {{ background: #f6f8fa; }}
    ul, ol {{ padding-left: 18pt; }}
    .doc {{ page-break-after: always; }}
    .doc:last-child {{ page-break-after: auto; }}
  </style>
</head>
<body>
{''.join(parts)}
</body>
</html>
"""

from weasyprint import HTML
HTML(string=html, base_url=str(BASE)).write_pdf(str(OUT))
print(OUT)
