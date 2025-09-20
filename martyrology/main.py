#!/usr/bin/env python3
# -*- coding: utf-8 -*-

r"""
Build a LaTeX martyrology from legacy FrontPage HTML files.

- Scans mart01 ... mart12 for .htm files
- Extracts the preface lines (Latin/English)
- Renders the 'letter of the martyrology' as two stacked tabularx blocks:
  * evenly spaced columns
  * no border
  * letters colored gregoriocolor
  * EXCEPT the first capital 'F' in the second (uppercase) letters row, which stays black
- Emits two-column text (Latin left, English right) using paracol
  * Dropcap (lettrine) on the first Latin paragraph and the first English paragraph
  * First letter of each subsequent paragraph colored gregoriocolor
  * 'R.' / 'r.' replaced by \Rbar (\rbar is provided as an alias)
- Produces martyrology.tex

Requirements:
  pip install beautifulsoup4 lxml
"""

import os
import re
import glob
import html
from bs4 import BeautifulSoup

# ----------------------------- Utilities -----------------------------

MONTHS = {
    "January","February","March","April","May","June",
    "July","August","September","October","November","December"
}

MONTHS_EN = [
    "January","February","March","April","May","June",
    "July","August","September","October","November","December"
]

MONTHS_LA = [
    "Ianuarius","Februarius","Martius","Aprilis","Maius","Iunius",
    "Iulius","Augustus","September","October","November","December"
]

def latex_escape(s: str) -> str:
    """Escape LaTeX-sensitive characters, keep Unicode accents."""
    if s is None:
        return ""
    s = html.unescape(s).replace("\xa0", " ").rstrip("\n")
    # Basic LaTeX escaping
    replacements = {
        '\\': r'\textbackslash{}',
        '{': r'\{',
        '}': r'\}',
        '#': r'\#',
        '$': r'\$',
        '%': r'\%',
        '&': r'\&',
        '_': r'\_',
        '^': r'\^{}',
        '~': r'\~{}',
    }
    out = []
    for ch in s:
        out.append(replacements.get(ch, ch))
    txt = ''.join(out)
    # collapse multiple whitespace but DO NOT add spaces between inline fragments
    txt = re.sub(r'[ \t\f\v]+', ' ', txt)
    # tidy up spaces before punctuation
    txt = re.sub(r'\s+([.,;:?!])', r'\1', txt)
    return txt.strip()

def fix_quotes_for_latex(s: str) -> str:
    """
    Convert straight quotes into proper TeX-style quotes.
    - "text" -> ``text''
    - 'text' -> `text'
    Handles nested punctuation reasonably well.
    """
    if not s:
        return s

    # Handle double quotes
    out = []
    dbl_open = True
    for ch in s:
        if ch == '"':
            if dbl_open:
                out.append("``")
            else:
                out.append("''")
            dbl_open = not dbl_open
        else:
            out.append(ch)
    s = "".join(out)

    # Handle single quotes (only if they are straight apostrophe, not part of words like don't)
    out = []
    sgl_open = True
    for i, ch in enumerate(s):
        if ch == "'":
            # naive check: if prev char is a letter, keep as apostrophe
            if i > 0 and s[i-1].isalpha():
                out.append("'")
            else:
                if sgl_open:
                    out.append("`")
                else:
                    out.append("'")
                sgl_open = not sgl_open
        else:
            out.append(ch)
    return "".join(out)

def clean_text(el) -> str:
    """Extract text without injecting spaces around inline tags."""
    if el is None:
        return ""
    for bad in el.find_all(['script', 'style']):
        bad.decompose()
    for br in el.find_all('br'):
        br.replace_with('\n')
    # keep original adjacency (prevents "Circumc í sio")
    txt = el.get_text(separator='', strip=False)
    return txt

def looks_like_month_heading(text: str) -> bool:
    if not text:
        return False
    parts = text.split()
    return len(parts) >= 2 and parts[0] in MONTHS

def is_spacer_row(tr) -> bool:
    """Detect rows that are just images/blank spacers."""
    tds = tr.find_all('td', recursive=False)
    if not tds:
        return True
    if tr.find('img'):
        return True
    txt = latex_escape(clean_text(tr))
    return len(txt) == 0


# preprocessors for the responses to make sure that they all end up on the same rows.
def _starts_with_response_token(s: str) -> bool:
    if not s: return False
    return bool(re.match(
        r'^\s*(?:'                                  # any of:
        r'[Rr]\s*\.'                                #  R.
        r'|' r'\\textcolor\{gregoriocolor\}\{\\Rbar\}'  # already replaced
        r')', s))

def merge_response_rows(pairs):
    """
    If a row begins with a response token, append it to the previous row (L/R separately).
    """
    merged = []
    for L, R in pairs:
        if merged and (_starts_with_response_token(L) or _starts_with_response_token(R)):
            prevL, prevR = merged[-1]
            if _starts_with_response_token(L):
                merged[-1] = ( (prevL + ' ' + L).strip(), prevR )
            if _starts_with_response_token(R):
                prevL, prevR = merged[-1]
                merged[-1] = ( prevL, (prevR + ' ' + R).strip() )
        else:
            merged.append((L, R))
    return merged

def replace_response_symbols_latin(s: str) -> str:
    r"""
    Inline Latin response:
      'R.' -> \textcolor{gregoriocolor}{\Rbar}.~Deo gr\'atias.
      If 'Deo grátias.' already follows, don't duplicate it.
    """
    if not s:
        return s

    pattern = re.compile(
        r"""\b[Rr]\s*\.\s*
            (D[eé]o\s+gr[aá]ti[aá]s\.)?
        """,
        re.VERBOSE,
    )

    def _sub(m: re.Match) -> str:
        has_phrase = m.group(1) is not None
        base = r'\textcolor{gregoriocolor}{\Rbar.}~'
        return base + (m.group(1) if has_phrase else r"Deo gr\'atias.")

    return pattern.sub(_sub, s)


def replace_response_symbols_english(s: str) -> str:
    r"""
    Inline English response:
      'R.' -> \textcolor{gregoriocolor}{\Rbar}.~Thanks be to God.
      If 'Thanks be to God.' already follows, don't duplicate it.
    """
    if not s:
        return s

    pattern = re.compile(
        r"""\b[Rr]\s*\.\s*
            (Thanks\s+be\s+to\s+God\.)?
        """,
        re.VERBOSE,
    )

    def _sub(m: re.Match) -> str:
        has_phrase = m.group(1) is not None
        base = r'\textcolor{gregoriocolor}{\Rbar.}~'
        return base + (m.group(1) if has_phrase else "Thanks be to God.")

    return pattern.sub(_sub, s)

# ----------------------------- Parsing ------------------------------

def parse_letter_tables(rows_iter):
    """
    From a row iterator *just after* the preface row, collect the inner
    letter/number tables (inside a single colspan=2 cell).
    """
    tables = []
    try:
        tr = next(rows_iter)
    except StopIteration:
        return tables, rows_iter

    inner_tables = tr.find_all('table')
    if inner_tables:
        for tb in inner_tables:
            data = []
            for r in tb.find_all('tr', recursive=False):
                row = []
                for td in r.find_all(['td','th'], recursive=False):
                    txt = latex_escape(clean_text(td))
                    row.append(txt)
                if any(cell for cell in row):
                    data.append(row)
            if data:
                tables.append(data)
        return tables, rows_iter
    else:
        # Put tr back into the stream
        def yield_back():
            yield tr
            for r in rows_iter:
                yield r
        return tables, yield_back()


def parse_file(path: str):
    # ---- local helpers for this function only ----
    CONCLUSION_LAT_RE = re.compile(r'Et\s+al[ií]bi', re.IGNORECASE)
    CONCLUSION_ENG_RE = re.compile(r'^\s*And elsewhere', re.IGNORECASE)

    def is_conclusion_pair(L: str, R: str) -> bool:
        """Detect the 'Et álibi … R. Deo grátias.' / 'And elsewhere … R. Thanks be to God.' row."""
        L = L or ""; R = R or ""
        return (
            (CONCLUSION_LAT_RE.search(L) and ("R." in L or "Deo gr" in L)) or
            (CONCLUSION_ENG_RE.search(R) and ("R." in R or "Thanks be to God" in R))
        )

    def is_jan_first(p: str) -> bool:
        """True only for January 1 files, e.g. .../mart01/mart0101.htm (or .html)."""
        pl = p.lower()
        in_jan = re.search(r'[/\\]mart01[/\\]', pl) is not None
        is_0101 = pl.endswith('mart0101.htm') or pl.endswith('mart0101.html')
        return in_jan and is_0101
    # ---------------------------------------------

    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        html_text = f.read()

    soup = BeautifulSoup(html_text, 'lxml')

    # Choose the largest table as the main content block
    tables = soup.find_all('table')
    main_table = None
    max_rows = -1
    for t in tables:
        rows = t.find_all('tr')
        if len(rows) > max_rows:
            main_table, max_rows = t, len(rows)
    if main_table is None:
        return None

    # Prefer an explicit month heading inside the main table; else fall back to <title>
    date_heading = None
    for ptag in main_table.find_all('p'):
        txt = clean_text(ptag)
        if looks_like_month_heading(txt):
            date_heading = latex_escape(txt)
            break
    if not date_heading:
        title_tag = soup.find('title')
        date_heading = latex_escape(clean_text(title_tag)) if title_tag else "Untitled"

    # Find the preface row: two tds with the characteristic Latin/English bold line
    rows = main_table.find_all('tr', recursive=False)
    preface_lat = preface_eng = None
    row_index = 0
    for i, tr in enumerate(rows):
        tds = tr.find_all('td', recursive=False)
        if len(tds) == 2:
            left_txt  = fix_quotes_for_latex(latex_escape(clean_text(tds[0])))
            right_txt = fix_quotes_for_latex(latex_escape(clean_text(tds[1])))
            if left_txt and right_txt and (
                "Luna" in left_txt or "Kaléndis" in left_txt or
                "January" in right_txt or "Day of the Moon" in right_txt
            ):
                preface_lat, preface_eng = left_txt, right_txt
                row_index = i + 1
                break

    # Gather the inner letter tables immediately after the preface
    def row_gen():
        for j in range(row_index, len(rows)):
            yield rows[j]
    rows_iter = row_gen()
    letter_tables, rows_iter = parse_letter_tables(rows_iter)

    # Remaining rows as body pairs (Latin left / English right)
    body_pairs = []
    for tr in rows_iter:
        if is_spacer_row(tr):
            continue
        tds = tr.find_all('td', recursive=False)
        if len(tds) == 2:
            L = fix_quotes_for_latex(latex_escape(clean_text(tds[0])))
            R = fix_quotes_for_latex(latex_escape(clean_text(tds[1])))
            if L or R:
                body_pairs.append((L, R))

    # Remove the "Et álibi… / And elsewhere…" conclusion everywhere except Jan 1
    if not is_jan_first(path):
        body_pairs = [pair for pair in body_pairs if not is_conclusion_pair(pair[0], pair[1])]

    return {
        "path": path,
        "date": date_heading,
        "preface_lat": preface_lat or "",
        "preface_eng": preface_eng or "",
        "letter_tables": letter_tables,
        "pairs": body_pairs,
    }

# ----------------------------- LaTeX emit ---------------------------


def latex_header():
    return r"""
\documentclass[11pt,twoside]{memoir}

% --- Memoir pagestyle: page number at the OUTER edge; months in headers ---
\newcommand{\LatinMonth}{}   % set from Python
\newcommand{\EnglishMonth}{}

\makepagestyle{marty}
% Even (left) pages: page# at outer (left), then Latin month
\makeevenhead{marty}{\thepage\qquad\textsc{\LatinMonth}}{}{}
% Odd (right) pages: English month, then page# at outer (right)
\makeoddhead{marty}{}{}{\textsc{\EnglishMonth}\qquad\thepage}
\makeevenfoot{marty}{}{}{}
\makeoddfoot{marty}{}{}{}
\pagestyle{marty}

% --- Engines & fonts (compile with XeLaTeX or LuaLaTeX) ---
\usepackage{fontspec}
\usepackage{polyglossia}
\setmainlanguage{english}
\setotherlanguage{latin}

\newif\ifminion
\IfFontExistsTF{Minion 3}{\miniontrue}{\minionfalse}
\ifminion
  \setmainfont{Minion 3}
  \newfontfamily\latinfont{Minion 3}
\else
  \setmainfont{Libertinus Serif}
  \newfontfamily\latinfont{Libertinus Serif}
\fi

% --- Gregorio & colors ---
\usepackage{gregoriotex}
\usepackage{xcolor}
\definecolor{gregoriocolor}{HTML}{C6171C} % for both text and (if used) gregorio

% Response symbol convenience
\providecommand{\rbar}{\Rbar}

% --- Layout & tables ---
\usepackage{paracol}
\usepackage{geometry}
\usepackage{tabularx}
\usepackage{array}
\usepackage{booktabs}
\usepackage{longtable}

% --- Typography / hyphenation ---
\usepackage{microtype}
\usepackage{needspace}
\geometry{margin=1in}
\setlength{\parskip}{0.6em}
\setlength{\parindent}{0pt}
\emergencystretch=2em

% --- Drop caps ---
\usepackage{lettrine}
\renewcommand{\LettrineFontHook}{\color{gregoriocolor}}

% --- Memoir pagestyle: page number at the OUTER edge; months in headers ---
\makepagestyle{marty}
% Even (left) pages: outer = left. Show page no. at left, Latin month after it.
\makeevenhead{marty}{\thepage\qquad\textsc{\leftmark}}{}{}
% Odd (right) pages: outer = right. Show English month before page no. at right.
\makeoddhead{marty}{}{}{\textsc{\rightmark}\qquad\thepage}
\makeevenfoot{marty}{}{}{}
\makeoddfoot{marty}{}{}{}
\pagestyle{marty}

\title{Roman Martyrology (Extracted)}
\author{}
\date{}
\begin{document}
\maketitle
"""

def latex_footer():
    return r"""
\end{document}
"""

def color_first_letter(s: str) -> str:
    """Color the first visible Latin/English letter."""
    if not s:
        return s
    m = re.search(r'([A-Za-zÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÄËÏÖÜáéíóúàèìòùâêîôûäëïöü])', s)
    if not m:
        return s
    i = m.start(1)
    ch = m.group(1)
    return s[:i] + r'\textcolor{gregoriocolor}{' + ch + '}' + s[i+1:]

# In latex_header() you already have:
# \usepackage{lettrine}
# \renewcommand{\LettrineFontHook}{\color{gregoriocolor}}

def dropcap_first_word(s: str) -> str:
    """Drop cap ONLY the first letter; rest of first word in small caps (lettrine default)."""
    if not s:
        return "~"
    # first letter (incl. accented) + rest of the first word + rest of paragraph
    m = re.match(r'\s*([A-Za-zÁÉÍÓÚÀÈÌÒÙÂÊÎÔÛÄËÏÖÜáéíóúàèìòùâêîôûäëïöü])([^\s]*)\s*(.*)$', s, flags=re.DOTALL)
    if not m:
        return s
    first_letter = m.group(1)
    rest_of_word = m.group(2)           # small caps via lettrine default
    remainder    = m.group(3) or ""
    # Color of the initial comes from \LettrineFontHook, so no \textcolor here
    return r'\lettrine[lines=2]{' + first_letter + r'}{' + rest_of_word + r'}' + (' ' + remainder if remainder else '')

def _normalize_inline_pars(s: str) -> str:
    """Collapse multiple blank lines to a single space to avoid stray paragraphs."""
    if not s:
        return s
    # turn multiple newlines into a single space (keeps single linebreaks harmless)
    s = re.sub(r'\n\s*\n+', ' ', s)
    return s

def emit_preface_two_col_centered(preface_lat, preface_eng):
    L = _normalize_inline_pars(preface_lat or "~")
    R = _normalize_inline_pars(preface_eng or "~")
    out = []
    out.append(r"\needspace{10\baselineskip}")   # keep preface + table together
    out.append(r"\begin{paracol}{2}")
    out.append(r"\selectlanguage{latin}")
    out.append(r"\begin{center}{\color{gregoriocolor} " + L + r"}\end{center}")
    out.append(r"\switchcolumn")
    out.append(r"\selectlanguage{english}")
    out.append(r"\begin{center}{\color{gregoriocolor} " + R + r"}\end{center}")
    out.append(r"\end{paracol}")
    return "\n".join(out)

def _color_cell_for_letters(cell: str, treat_first_F_black: bool):
    """
    Color letters with gregoriocolor, numbers left black.
    If treat_first_F_black=True, the FIRST 'F' cell encountered remains black;
    subsequent 'F' (if any) are colored.
    """
    s = cell.strip()
    if not s:
        return s
    if s.isdigit():
        return s
    if len(s) == 1 and s.isalpha():
        if treat_first_F_black and s == "F":
            return "__FIRST_F__"
        return r"\textcolor{gregoriocolor}{" + s + "}"
    if s.isalpha():
        if treat_first_F_black and s == "F":
            return "__FIRST_F__"
        return r"\textcolor{gregoriocolor}{" + s + "}"
    return s

def emit_letter_tables_compact_no_border(tables):
    """
    Render the 'letter of the martyrology' as two stacked tabularx blocks,
    full width, evenly spaced columns, no border.
    - All letters colored gregoriocolor
    - In the SECOND (uppercase) letter row, the FIRST capital F stays black.
    """
    if not tables:
        return ""
    out = []
    for t_index, tb in enumerate(tables):
        if not tb:
            continue
        ncols = max(len(r) for r in tb)
        # On the *second* table (index 1), keep the first F black.
        treat_first_F_black = (t_index == 1)

        colored_rows = []
        first_F_done = False
        for r in tb:
            row = r + [""] * (ncols - len(r))
            colored = []
            for cell in row:
                v = _color_cell_for_letters(cell, treat_first_F_black and not first_F_done)
                if v == "__FIRST_F__":
                    colored.append("F")  # black
                    first_F_done = True
                else:
                    colored.append(v)
            colored_rows.append(colored)

        coldef = r"*{%d}{>{\centering\arraybackslash}X}" % ncols
        out.append(r"\noindent\begin{tabularx}{\linewidth}{" + coldef + "}")
        for cr in colored_rows:
            out.append(" {} \\\\".format(" & ".join(cr)))
        out.append(r"\end{tabularx}")

        if t_index != len(tables) - 1:
            out.append(r"\vspace{0.5\baselineskip}")
    return "\n".join(out)


def emit_body_paracol_with_dropcaps(pairs):
    # language-specific response replacements (inline)
    norm = []
    for L, R in pairs:
        Lp = replace_response_symbols_latin(L or "")
        Rp = replace_response_symbols_english(R or "")
        norm.append((Lp, Rp))

    # merge response-only rows into previous paragraph
    norm = merge_response_rows(norm)

    out = []
    out.append(r"\begin{paracol}{2}")
    out.append(r"\selectlanguage{latin}")

    first_pair = True
    for Lp, Rp in norm:
        if first_pair:
            left  = dropcap_first_word(Lp) if Lp else "~"
            right = dropcap_first_word(Rp) if Rp else "~"
            first_pair = False
        else:     # no coloring on later paragraphs
            left  = (Lp or "~")
            right = (Rp or "~")

        out.append(left)
        out.append(r"\switchcolumn")
        out.append(r"\selectlanguage{english}")
        out.append(right)
        out.append(r"\switchcolumn*")
        out.append(r"\selectlanguage{latin}")

    out.append(r"\end{paracol}")
    return "\n".join(out)

def write_latex(documents, outfile="martyrology.tex"):
    def month_from_folder(path: str):
        folder = os.path.split(path)[0]              # e.g., 'mart01'
        base   = os.path.basename(folder)
        m = re.match(r'martyrology/mart(\d\d)', base, flags=re.I)
        if not m:
            return None
        idx = int(m.group(1))  # 01..12
        if 1 <= idx <= 12:
            return idx
        return None

    with open(outfile, "w", encoding="utf-8") as f:
        f.write(latex_header())

        current_month = None
        for doc in documents:
            month_idx = month_from_folder(doc["path"])

            if month_idx and month_idx != current_month:
                current_month = month_idx
                la = MONTHS_LA[month_idx-1]
                en = MONTHS_EN[month_idx-1]
                f.write(r"\cleartorecto" + "\n")
                # Set header macros directly
                f.write(r"\gdef\LatinMonth{" + la + "}" + "\n")
                f.write(r"\gdef\EnglishMonth{" + en + "}" + "\n\n")

            f.write("\n% ---- {}\n".format(doc["path"]))

            # Preface ABOVE the letter table (kept with table)
            f.write(emit_preface_two_col_centered(doc["preface_lat"], doc["preface_eng"]))
            f.write("\n\n")

            # Letter tables: no border, colored letters, special F rule
            f.write(emit_letter_tables_compact_no_border(doc["letter_tables"]))
            f.write("\n\n")

            # Body with dropcaps and colored initials + response normalization
            f.write(emit_body_paracol_with_dropcaps(doc["pairs"]))
            f.write("\n\n")

        f.write(latex_footer())


# ----------------------------- Main --------------------------------

def main():
    # Collect .htm files
    paths = []
    for m in range(1, 13):
        folder = f"martyrology/mart{m:02d}"
        paths.extend(glob.glob(os.path.join(folder, "*.htm")))
    paths.sort(key=lambda p: (p.split(os.sep)[0], p))

    docs = []
    for p in paths:
        parsed = parse_file(p)
        if parsed:
            docs.append(parsed)

    if not docs:
        print("No documents parsed. Check mart01..mart12 folders.")
        return

    write_latex(docs, "martyrology.tex")
    print(f"Wrote martyrology.tex with {len(docs)} days.")

if __name__ == "__main__":
    main()

