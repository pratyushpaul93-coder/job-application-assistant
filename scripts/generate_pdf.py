import os, sys, re

LINKEDIN = "https://www.linkedin.com/in/pratyushpaul/"
GITHUB = "https://github.com/pratyushpaul93-coder"
CSS = '@page { size: letter; margin: 0.5in 0.55in 0.5in 0.55in; }\n* { box-sizing: border-box; margin: 0; padding: 0; }\nbody { font-family: Carlito, Calibri, Arial, sans-serif; font-size: 10pt; line-height: 1.30; color: #111; }\n.name { font-size: 18pt; font-weight: 700; margin-bottom: 2pt; }\n.contact { font-size: 9pt; color: #333; margin-bottom: 8pt; }\n.contact a { color: #1a56db; text-decoration: none; }\n.section-title { font-size: 9.5pt; font-weight: 700; text-transform: uppercase; border-bottom: 1pt solid #111; margin-top: 8pt; margin-bottom: 4pt; padding-bottom: 1pt; }\n.company-name { font-weight: 700; font-size: 10pt; margin-bottom: 0pt; }\n.role-line { display: flex; justify-content: space-between; margin-bottom: 2pt; }\n.role-title-text { font-style: italic; font-weight: 400; font-size: 10pt; }\n.role-date { font-weight: 400; font-size: 9.5pt; color: #222; }\nul { margin-left: 11pt; margin-bottom: 5pt; padding: 0; list-style-type: disc; }\nli { margin-bottom: 1pt; font-size: 9.5pt; line-height: 1.30; }\n.summary { margin-bottom: 1pt; font-size: 10pt; }\n.edu-line { display: flex; justify-content: space-between; margin-bottom: 2pt; }\n.sql-note { font-size: 8.5pt; color: #b45309; font-weight: 600; margin-bottom: 5pt; border-left: 2pt solid #f59e0b; padding-left: 4pt; }\np { margin-bottom: 1pt; }\n'

SECTIONS = ["SUMMARY", "CORE EXPERIENCE", "EXPERIENCE",
            "EDUCATION AND INTERNSHIPS", "EDUCATION",
            "AI/TECHNICAL PERSONAL PROJECTS", "AI/TECHNICAL PROJECTS", "SKILLS"]

DATE_RE = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|20\d\d|Present)"

def has_date(s):
    return bool(re.search(DATE_RE, s))

def to_html(text):
    lines = [l.rstrip() for l in text.strip().split("\n")]
    html = []
    in_list = False
    current_section = ""
    i = 0

    def close_list():
        nonlocal in_list
        if in_list:
            html.append("</ul>")
            in_list = False

    # Name
    html.append(f'<p class="name">{lines[0].strip()}</p>')
    i = 1

    # Contact line
    if i < len(lines) and ("@" in lines[i] or "(" in lines[i]):
        c = lines[i].strip()
        c = re.sub(r"\bLinkedIn\b", f'<a href="{LINKEDIN}">LinkedIn</a>', c)
        if "GitHub" not in c:
            c += f' | <a href="{GITHUB}">GitHub</a>'
        html.append(f'<p class="contact">{c}</p>')
        i += 1

    # SQL note scan
    for line in lines:
        if "[SQL NOTE:" in line:
            html.append(f'<p class="sql-note">{line.strip()}</p>')
            break

    while i < len(lines):
        line = lines[i].strip()
        i += 1

        if not line:
            continue
        if "[SQL NOTE:" in line:
            continue

        # Section header
        matched = next((s for s in SECTIONS if line.upper().startswith(s)), None)
        if matched:
            close_list()
            display = line.rstrip(":")
            if "EDUCATION" in display.upper() and "INTERN" not in display.upper():
                display = "Education and Internships"
            html.append(f'<div class="section-title">{display}</div>')
            current_section = matched
            continue

        # Summary text (first non-empty line after SUMMARY)
        if current_section == "SUMMARY" and not line.startswith("-"):
            close_list()
            html.append(f'<p class="summary">{line}</p>')
            current_section = "SUMMARY_DONE"
            continue

        # Education lines
        if current_section in ["EDUCATION AND INTERNSHIPS", "EDUCATION"]:
            if "|" in line:
                parts = [p.strip() for p in line.split("|")]
                date = parts[-1] if has_date(parts[-1]) else ""
                if date and len(parts) >= 2:
                    org = parts[0]
                    role_parts = parts[1:-1]
                    role = " | ".join(role_parts) if role_parts else ""
                    left = f'<strong>{org}</strong>'
                    if role:
                        left += f' | <em>{role}</em>'
                    html.append(f'<div class="edu-line"><span>{left}</span><span class="role-date">{date}</span></div>')
                    continue
            close_list()
            html.append(f"<p>{line}</p>")
            continue

        # Core experience: COMPANY line detection
        # Pattern: line has NO date, NO bullet, NO pipe, not too long -> likely company
        # AND next non-empty line has a date and a pipe (title | date)
        if current_section in ["CORE EXPERIENCE", "EXPERIENCE"]:
            if (not line.startswith("-") and not has_date(line) and "|" not in line and len(line) < 70):
                # Look ahead for title | date line
                j = i
                while j < len(lines) and not lines[j].strip():
                    j += 1
                next_line = lines[j].strip() if j < len(lines) else ""
                if "|" in next_line and has_date(next_line):
                    # This is a company line
                    close_list()
                    # Split company name from location on first comma
                    if ',' in line:
                        co_name, co_loc = line.split(',', 1)
                        html.append(f'<p class="company-name"><strong>{co_name.strip()}</strong>, {co_loc.strip()}</p>')
                    else:
                        html.append(f'<p class="company-name"><strong>{line}</strong></p>')
                    # Consume the title | date line
                    i = j + 1
                    parts = [p.strip() for p in next_line.rsplit("|", 1)]
                    title = parts[0]
                    date = parts[1] if len(parts) > 1 else ""
                    html.append(
                        f'<div class="role-line">' +
                        f'<span class="role-title-text">{title}</span>' +
                        f'<span class="role-date">{date}</span></div>'
                    )
                    continue

        # Bullet
        if line.startswith("-"):
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{line[1:].strip()}</li>")
            continue

        close_list()
        html.append(f"<p>{line}</p>")

    close_list()
    return "\n".join(html)

def make_pdf(css_override, text, pdf_path):
    import weasyprint
    content = to_html(text)
    css_used = CSS.replace(
        "line-height: 1.30;",
        f"line-height: {css_override['line_height']};"
    ).replace(
        "font-size: 10pt;",
        f"font-size: {css_override['font_size']}pt;"
    )
    full = (
        "<!DOCTYPE html><html lang='en'><head><meta charset='UTF-8'>"
        f"<style>{css_used}</style></head><body>{content}</body></html>"
    )
    tmp_path = pdf_path + ".tmp.pdf"
    weasyprint.HTML(string=full).write_pdf(tmp_path)
    rendered = weasyprint.HTML(string=full).render()
    pages = len(rendered.pages)
    return full, pages, tmp_path

def generate(txt_path, pdf_path):
    import weasyprint, shutil
    text = open(txt_path).read()

    attempts = [
        {"line_height": "1.28", "font_size": "10"},
        {"line_height": "1.22", "font_size": "10"},
        {"line_height": "1.16", "font_size": "10"},
        {"line_height": "1.16", "font_size": "9.5"},
        {"line_height": "1.12", "font_size": "9.5"},
    ]

    for attempt in attempts:
        full, pages, tmp = make_pdf(attempt, text, pdf_path)
        print(f"  Attempt line-height={attempt['line_height']} font={attempt['font_size']}pt -> {pages} page(s)")
        if pages == 1:
            shutil.move(tmp, pdf_path)
            html_path = pdf_path.replace(".pdf", ".html")
            open(html_path, "w").write(full)
            kb = os.path.getsize(pdf_path) // 1024
            print(f"PDF: {pdf_path} ({kb}KB) - fits 1 page")
            return
        else:
            os.remove(tmp)

    # Last resort: move final attempt anyway and warn
    shutil.move(tmp, pdf_path)
    print(f"WARNING: Could not fit to 1 page after all attempts. Content needs trimming.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python3 generate_pdf.py <input.txt> <output.pdf>")
        sys.exit(1)
    generate(sys.argv[1], sys.argv[2])
