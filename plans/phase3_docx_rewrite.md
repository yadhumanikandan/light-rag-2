# Phase 3 — DOCX Rewrite (NAAS v4.0 Format)

Goal: rework `app/kyc_generator.py` so the generated KYC Profile Word doc matches the NAAS spec — 20 standard sections, A–G checklist, flags section, version-tracked header/footer, and the closing disclaimer.

Depends on: Phase 1 (analysis dict) and Phase 2 (structured extractor fields). Read from `report["analysis"]` produced in Phase 1.

## Output structure (per spec Step 8)

Header (every page): `KYC PROFILE — [COMPANY NAME] | CONFIDENTIAL | v[N] — [Date]`
Footer (every page): `Prepared by NAAS — National Assurance & Advisory Services FZ LLC | [Date] | CONFIDENTIAL`

Body sections, in order:

| # | Title | Source |
|---|-------|--------|
| 1 | Company Details | MOA / TL |
| 2 | Trade Licence Details | TL + Receipt |
| 3 | Registered Address & Contact | TL / EJARI |
| 4 | EJARI — Tenancy Contract | EJARI |
| 5 | VAT Registration | VAT |
| 6 | Insurance | TL / Insurance |
| 7 | Business Activities | TL / MOA |
| 8 | Share Capital & Ownership | MOA / Partners Annex |
| 9 | Owner / Shareholder Details | MOA + EID + PP + Visa |
| 10 | Management Details | MOA + EID |
| 11 | Banking & Signatory Authority | MOA / BR |
| 12 | Board Resolution Status | MOA assessment |
| 13 | Physical Presence & POA Status | Presence check + POA |
| 14 | Corporate Shareholder KYC | Entity docs + UBO + attestation |
| 15 | Address Verification — Cross-Document | TL vs EJARI vs VAT |
| 16 | Name Verification — TL vs MOA | Cross-check table |
| 17 | Personal Documents Verification | EID + PP + Visa per person |
| 18 | KYC Verification Checklist | A–G |
| 19 | Discrepancies & Flags | All flags |
| 20 | Documents Reviewed | Upload list |

End matter: NAAS disclaimer (verbatim from spec).

## Formatting standards

- Font: Arial throughout.
- Page: A4, 1-inch margins.
- Section headers: dark navy `#1B3A6B` background, white bold Arial.
- Two-column data tables (Label | Value), alternating white / light grey rows.
- Status row colours: green pass (`✓`), red fail (`✗`), amber warn (`⚠`).
- Match tables: 4 columns (Field | Doc A | Doc B | Match ✓/✗).

## Build order

1. **Infrastructure helpers.**
   - `_set_header(doc, company, version, today)` and `_set_footer(doc, today)`.
   - `_add_section_heading(doc, text)` with the navy + white styling.
   - `_add_kv_table(doc, rows)` — two-column zebra-striped.
   - `_add_match_table(doc, header, rows)` — 4-column with check/cross.
   - `_add_status_row(doc, label, status)` — green/red/amber background.
   - Centralise the navy + greys as constants.

2. **Section renderers.** One function per section, each takes `(doc, extracted, analysis, today)`. Each is independent and writes its own heading + tables. Sections that have no source data render a single italic line `Not provided.` and continue (do not skip headings — keeps document numbering stable).

3. **Builder entry point.** Replace the current single-pass `generate_kyc_document` with:
   ```python
   def generate_kyc_document(extracted, analysis, today):
       doc = Document()
       _apply_page_setup(doc)
       _set_header(doc, ...); _set_footer(doc, ...)
       for renderer in SECTION_RENDERERS:
           renderer(doc, extracted, analysis, today)
       _add_disclaimer(doc)
       return _serialise(doc)
   ```
   Update `main.py:_generate_and_respond` to pass `analysis` through.

4. **Section 11 — Banking & Signatory Authority.** Render the 5D table from spec verbatim:
   - MOA Type, Authorised Signatory, Signing Mode, Bank Account Opening, Cheque Signing, Fund Transfer, Delegate via POA, Board Resolution Required.
   Pull all values from `analysis.moa_authority`.

5. **Section 12 — Board Resolution Status.** If `moa_authority.sufficient` → green "MOA sufficient — no Board Resolution required". Else → amber block listing the spec 5C minimum-content requirements verbatim.

6. **Section 13 — Physical Presence & POA Status.** Render the 6D table:
   - Person | Role | Authority Source | In UAE | EID | Visa | Passport | Can Proceed | Action
   - One row per person from `analysis.presence`.
   - If POA present, append a sub-block showing grantee details + the 6C eligibility checklist.

7. **Section 14 — Corporate Shareholder KYC.** For each entry in `analysis.corporate_kyc`:
   - Heading "[Entity Name] — [share_pct]% — [jurisdiction]".
   - Required-docs checklist (✅ provided / ❌ missing).
   - Attestation 4-stage table from `attestation.stage1..stage4`.
   - Country-specific note from spec 7E if jurisdiction matches a known country.

8. **Sections 15 & 16 — Cross-Verification tables.** Use `analysis.cross_checks.addresses` and `cross_checks.person_names` to render 4-column match tables.

9. **Section 17 — Personal Documents Verification.** For each person in presence list:
   - Mini KV block: name, role, EID#, PP#, Visa#, expiry of each, status badge.

10. **Section 18 — KYC Verification Checklist.** Iterate `analysis.checklist.A..G`. Each item rendered as `☑/☐/⚠ <label> — <detail>`.

11. **Section 19 — Discrepancies & Flags.** For each `analysis.flags` entry, render the spec block format verbatim:
    ```
    ⚠️/❌ FLAG [n]: <type>
    Documents Affected : ...
    Field              : ...
    Issue              : ...
    Recommended Action : ...
    KYC Status         : ...
    ```
    If flag list is empty: green "No discrepancies identified".

12. **Section 20 — Documents Reviewed.** Auto-list from `extracted.keys()` plus `partner_personal_docs[*]`. Show document type, filename(s) reviewed, and a status badge.

13. **Disclaimer.** Verbatim NAAS disclaimer from spec end-matter, italic, smaller font.

14. **`build_report_data` (preview JSON).** Mirror the new section structure so the frontend preview can show the same content without re-parsing the DOCX. Include `analysis` verbatim under `report.analysis`.

## Files touched

- `app/kyc_generator.py` — major rewrite. Keep `identify_partners` exported (Phase 2 reads it). Keep `_names_match` and `_s` exported or move to a shared util.
- `app/main.py` — pass `analysis` into `generate_kyc_document` and `build_report_data`. No endpoint signature changes.

## Out of scope for Phase 3

- Frontend changes (Phase 4).
- Adding new extractor doc types (Phase 2).
- Persisting an HTML or PDF version.

## Verification

1. Generate a report from the existing sample. All 20 sections present in order; header/footer show correct version + date.
2. Section 11/12 reflect the MOA authority verdict from analysis.
3. Section 19 lists flags using the verbatim block format.
4. Section 20 lists every uploaded document.
5. Disclaimer present, verbatim, at the end.
6. Open the docx in Word and confirm: navy section headers, zebra-striped tables, check/cross emojis render, page numbers if used render correctly.

## Definition of done

- Generated DOCX matches the spec layout for the sample.
- Version string in header tracks per spec Version Tracking table.
- No regression in NAS archiving.
- Frontend preview JSON contains the same structured data the DOCX renders.
