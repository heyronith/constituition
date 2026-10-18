# PHASE 9H — Word (.docx) cover letter and Contribution Information Sheet

**Date:** 2026-10-17  
**Prior tag:** `mlj-submission-v4` (`cf867b3`) — left in place  
**This tag:** `mlj-submission-v5`  
**Scope:** Word exports only. `.tex` sources unchanged in wording; manuscript/figures/`paper/`/`analysis/`/`results/` untouched. Docx files are **not** added to `submission_mlj.zip`.

---

## Method

| Piece | Choice |
|---|---|
| Builder | `scripts/make_mlj_word.py` + `make mlj-word` |
| Conversion | **python-docx from `.tex`** (not free-typed). Pandoc is available on the machine but was not used for the final documents: cover-letter layout (sender/recipient/signature) and CIS run-in bold labels + bullets are more reliable built directly. |
| Reference | `paper_mlj/word/reference.docx` — US Letter, 1″ margins, Times New Roman 11 pt, single spacing, 6 pt after paragraphs |
| `\today` | Replaced with the date string from `cover_letter.pdf`: **October 17, 2026** |

Outputs:

- `paper_mlj/word/cover_letter.docx`
- `paper_mlj/word/contribution_information_sheet.docx`
- copies in `submission_mlj/` (alongside PDFs; excluded from the zip)

---

## Text-identity result

Normalisation (both PDF via `pdftotext` and docx paragraphs): lowercase; join hyphenation line-breaks; unify typographic quotes/dashes/×/α for compare; drop page-number-only lines and list markers; strip whitespace; strip intra-word hyphens (PDF line-wrap artifact).

| Pair | Result |
|---|---|
| `cover_letter.docx` ↔ `cover_letter.pdf` | **PASS** |
| `contribution_information_sheet.docx` ↔ `contribution_information_sheet.pdf` | **PASS** |

`TODO` in either docx: **0**. No stray LaTeX (`\`, `{`, `}`, `~`).

---

## Page counts

LibreOffice / `soffice` is **not installed** on this machine (`soffice` / `libreoffice` / `/Applications/LibreOffice.app` missing). Headless PDF conversion for page-count verification was therefore **skipped**.

Formatting was checked by inspecting the docx XML/runs instead:

| Document | Notes |
|---|---|
| Cover letter | 18 paragraphs; 3 italic runs (*Machine Learning*); 1 live OSF hyperlink; en dashes (–); curly title quotes; sender / date / recipient / Dear Editor / body / Thank you / Sincerely + signature present |
| Contribution sheet | 16 paragraphs; 18 bold runs (numbered questions + Main claim / Why it matters / Design / Results + citation labels); bullets via List Bullet; Unicode × α − – — present |

PDF sources remain 1 page (cover) and 2 pages (sheet). Word layout uses the same 1″ margins and 11 pt Times New Roman.

---

## Zip policy

`unzip -l submission_mlj.zip` contains **no** `.docx` files. Author can upload PDF or Word separately.
