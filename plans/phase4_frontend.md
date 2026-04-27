# Phase 4 — Frontend Updates

Goal: surface the new compliance signals (status badges, flags, presence/authority verdicts) in `frontend/index.html` and add upload fields for the new corporate-shareholder document types introduced in Phase 2.

Depends on: Phase 1 (analysis dict in response), Phase 2 (new doc types), Phase 3 (preview JSON shape).

## Deliverables

1. New upload tiles in the KYC tab for: Certificate of Incorporation, Register of Shareholders, Register of Directors, Certificate of Good Standing (and Corporate MOA/AOA, Audited Financials if Phase 2 added them).
2. Compliance summary panel in the result view:
   - Overall KYC status badge (`COMPLETE`, `INCOMPLETE`, `ON HOLD`, `BLOCKED`, `COMPLIANCE GAP`) — derived from highest-severity flag.
   - Validity grid: row per dated doc with green/amber/red pill.
   - Banking authority block: signing mode + powers + "Board Resolution required: yes/no".
   - Presence table: one row per signatory with the 6D columns.
   - Flags list: each flag in spec block format (collapsible).
3. Multi-partner phase-2 form already exists — extend it so each partner can also upload Visa (already there) plus, if classified corporate, a "Corporate Documents" sub-form.

## Build order

1. **API contract sanity check.** Inspect the actual `/generate-kyc` response (after Phase 1+3 land) and lock the JSON paths the frontend reads:
   - `report.analysis.flags`
   - `report.analysis.validity`
   - `report.analysis.moa_authority`
   - `report.analysis.presence`
   - `report.analysis.shareholders`
   - `report.analysis.corporate_kyc`
   - `report.analysis.checklist`

2. **Upload tiles.** In the existing KYC tab grid, add new tiles for the corporate-shareholder docs. Use the same drag-drop / file-input component currently used for the 11 existing tiles. Field names must match Phase 2's `VALID_DOC_TYPES` additions exactly.

3. **Status helpers (JS).** Tiny pure functions:
   - `statusBadge(status)` → returns `<span class="badge badge--green">VALID</span>` etc.
   - `flagSeverityClass(severity)` → maps to amber/red.
   - `formatFlag(flag)` → returns the spec block-format HTML.

4. **Compliance summary panel.** New section rendered above the existing JSON dump:
   - Top-line overall status badge.
   - Validity grid (table).
   - Banking & Authority block.
   - Presence table.
   - Flags list (each flag a card; severity-coloured left border).
   Each block is collapsible; default open.

5. **Existing JSON preview.** Keep a "Raw extraction" collapsible at the bottom for debugging — no styling effort, just `<pre>{JSON}</pre>`.

6. **Download button.** Continue to fetch the base64 docx as today; rename button to "Download KYC Profile (v[N]).docx" using `report.analysis.version`.

7. **Multi-partner flow.** When the phase-1 response sets `needs_partner_docs: true`:
   - For each partner, also show their classified type (`natural` / `corporate`) from `report.analysis.shareholders` if present.
   - For corporate partners, swap the EID/PP/Visa upload triplet for the corporate-doc upload set.

## Styling

- Badges: pill-shaped, 12px, semibold. Colours: green `#1f8a3a`, amber `#b76e00`, red `#b3261e`, navy `#1B3A6B` (matches DOCX).
- Flag cards: white card, 4px left border in flag colour, header row with code + severity.
- No new dependencies. Plain CSS in the existing `<style>` block.

## Files touched

- `frontend/index.html` — only file. No build step exists.

## Out of scope for Phase 4

- New backend endpoints.
- Changing extraction logic.
- A separate flags export (PDF, CSV).
- Authentication / login.

## Verification

1. Upload an MOA-only document — frontend renders the MOA banking authority block plus `FLAG_01` if applicable.
2. Upload an expired EID — flag card shows `FLAG_04` with red severity, presence row shows red.
3. Upload a TL with a corporate partner — Section 14 in the panel shows the entity, missing-docs list, and an attestation 4-stage row of empty checks.
4. Upload all 11 existing doc types plus all 4 new corporate-shareholder doc types — overall status renders `COMPLETE` (assuming no flags) and download button shows correct version.
5. Mobile width (375px): panel remains readable; tables horizontally scroll.

## Definition of done

- All new upload tiles wired up and submitting to `/generate-kyc`.
- Compliance summary panel renders the 5 sub-blocks correctly for the sample data.
- No regression in the existing single-doc Document Expiry Checker tab.
- Downloaded DOCX still works exactly as before.
