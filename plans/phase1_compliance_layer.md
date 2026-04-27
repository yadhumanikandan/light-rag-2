# Phase 1 — Compliance / Analysis Layer

Goal: add a pure-logic layer that consumes already-extracted KYC data and produces validity, cross-verification, MOA banking authority, presence/POA, shareholder classification, attestation status, and a typed flag list. No LLM calls. No DOCX changes yet. No prompt changes yet.

This phase is the foundation everything else (Phase 3 rendering, Phase 4 frontend) reads from.

## Deliverable

A single new module: `app/kyc_compliance.py`.

Public entry point:

```python
def analyse(extracted: dict, today: date) -> dict
```

Returns a dict with these top-level keys (consumed in Phase 3):

```
{
  "validity":       { doc_key: {expiry_date, days_remaining, status} },
  "cross_checks":   { company_name, person_names, addresses, licence_number,
                      dob, passport_number, employer },
  "moa_authority":  { sufficient: bool, signing_mode, powers: {...},
                      resolution_required: bool, reason },
  "presence":       [ { person, role, in_uae, eid_valid, visa_valid,
                        passport_valid, can_proceed, action } ],
  "shareholders":   [ { name, type: "natural"|"corporate", share_pct,
                        nationality, jurisdiction? } ],
  "corporate_kyc":  [ { entity, share_pct, required_docs: [...],
                        provided: [...], missing: [...],
                        attestation: {stage1..stage4} } ],
  "checklist":      { A: [...], B: [...], C: [...], D: [...],
                      E: [...], F: [...], G: [...] },   # spec Step 9
  "flags":          [ { code, severity, kyc_status, ... } ],
  "version":        "v1" | "v2" | ...                   # see Versioning below
}
```

## Build order (small, testable steps)

1. **Skeleton + types.** Create `kyc_compliance.py` with `analyse(extracted, today)` returning the dict shape above with empty values. Wire it into `main.py:_generate_and_respond` (compute it, attach to the report dict — generator can ignore it for now).

2. **Validity (`_compute_validity`).** For every dated doc in `extracted`, parse `expiry_date` and compute days_remaining + status:
   - `> 30` → `valid`
   - `0..30` → `expiring_soon`
   - `< 0` → `expired`
   - VAT cert → `{status: "ongoing", note: "Ongoing registration — no expiry date"}`
   - Apply to: trade_license, ejari, insurance, emirates_id, passport, residence_visa, board_resolution.validity_until, poa.validity_until.

3. **Cross-checks (`_cross_check`).** Pure string-comparison helpers (case-insensitive, whitespace-collapsed):
   - company_name across TL / MOA / EJARI / VAT / EID employer / Visa employer
   - person_names: build a row per known person (owner, manager, partners) showing the value found in each doc + match flag
   - addresses: TL vs EJARI vs VAT vs MOA
   - licence_number: TL vs EJARI vs VAT
   - DOB: EID vs Passport
   - Passport No.: Passport vs Visa vs MOA
   - employer: EID employer / Visa employer vs TL company name
   Reuse `_names_match` and `_s` from `kyc_generator.py` (move them into `kyc_compliance.py` if cleaner — keep generator imports working).

4. **MOA authority (`_assess_moa_authority`).** Read the MOA extraction. Look for explicit banking-power phrases (open/close accounts, sign cheques, transfer/withdraw, delegate via POA). Decide:
   - `sufficient = True` if any banking power phrase present and a named manager/signatory.
   - else `sufficient = False`, `reason = "MOA silent on banking authority"`.
   - `signing_mode`: "individual" | "joint" | "unknown" — derive from MOA text.
   - `powers`: dict of bank_account_opening / cheque_signing / fund_transfer / delegate_via_poa each as bool|null.
   - `resolution_required` = `not sufficient` (also true if MOA names a different manager than current signatory — detectable when board_resolution.signatory differs from MOA.manager).
   Note: the extractor doesn't yet emit these MOA banking-power fields cleanly. For Phase 1, do best-effort parsing on whatever MOA text/fields exist; Phase 2 will add structured fields to the extractor.

5. **Presence / POA (`_check_presence`).** For each named signatory (MOA manager + any board_resolution.signatory + any POA grantee):
   - Pull their EID/Passport/Visa from `extracted["partner_personal_docs"]` or top-level.
   - Compute `in_uae` = has valid Residence Visa.
   - Validity flags from step 2.
   - `can_proceed` = all three valid AND in_uae.
   - `action` = `"None"` | `"POA"` | `"Renew <doc>"` | `"Travel to UAE"`.
   Also handle POA grantee separately and verify their docs were provided.

6. **Shareholder classification (`_classify_shareholders`).** Read partners_annex (preferred) else trade_license partners. For each partner:
   - If a "person number" / Emirates ID-shaped number is present and a nationality + first/last name → `type: "natural"`.
   - If the entry contains "LLC" / "Ltd" / "PJSC" / "DMCC" / "Sarl" / "GmbH" / "Inc" / "Corp" / "Co." / "Company" / lacks a person number → `type: "corporate"`.
   - Capture share_pct.

7. **Corporate KYC checklist (`_corporate_kyc`).** For each corporate shareholder:
   - If share_pct == 100 → required_docs = 10-doc list (spec 7A).
   - Else → 8-doc list (spec 7B).
   - `provided`: cross-reference what's present in `extracted` (the extractor doesn't surface these yet — Phase 2 work; for now leave `provided=[]` and `missing=required_docs`).
   - `attestation`: stages 1–4 each `unknown` until Phase 2 supplies them.

8. **Checklist (`_build_checklist`).** Map the prior outputs to spec Step 9 sections A–G. Each entry: `{label, status: "pass"|"fail"|"warn"|"na", detail}`.

9. **Flags (`_build_flags`).** Emit standardised entries matching the 12 flag types from upgrade.md. Each flag:
   ```
   {code: "FLAG_01_BANKING_AUTHORITY_MISSING",
    severity: "warn"|"error",
    kyc_status: "INCOMPLETE"|"ON_HOLD"|"BLOCKED"|"COMPLIANCE_GAP",
    documents_affected: [...],
    field: "...",
    issue: "...",
    recommended_action: "..."}
   ```
   Map: MOA silent → FLAG_01; resolution missing when required → FLAG_02; signatory not in UAE → FLAG_03; expired personal doc → FLAG_04; POA grantee unverified → FLAG_05; VAT address mismatch → FLAG_06; name mismatch → FLAG_07; missing personal doc → FLAG_08; corporate shareholder docs missing → FLAG_09; attestation incomplete → FLAG_10; translation missing → FLAG_11; corporate partner board resolution missing → FLAG_12.

10. **Versioning.** Compute version per spec table:
    - v1 = TL only; v2 += MOA; v3 += EJARI; v4 += personal docs; v5 += VAT; v6 += BR/POA; v7 += corporate shareholder docs.
    Pick the highest version whose required inputs are all present.

## Files touched

- `app/kyc_compliance.py` — new.
- `app/main.py` — compute analysis once and pass it through `_generate_and_respond` (no rendering changes).
- `app/kyc_generator.py` — accept the new analysis dict in `build_report_data` and stash it under `report["analysis"]` so the frontend can read it without DOCX changes (rendering happens in Phase 3).

## Out of scope for Phase 1

- Changing extractor prompts (Phase 2).
- Rewriting DOCX sections (Phase 3).
- Frontend display of flags (Phase 4).
- Persisting analysis to NAS.

## Verification

1. Run end-to-end with the existing sample (`ASAAS AL TAMYUZ DATES & SWEETS L.L.C-Irshad/`). Confirm `/generate-kyc` response now includes `report.analysis` with all top-level keys populated and the existing DOCX is byte-identical to before.
2. Spot-check on an expired EID — flag list should contain `FLAG_04`.
3. Spot-check on an MOA without explicit banking authority — `moa_authority.sufficient == False` and `FLAG_01` present.
4. Spot-check on a TL with two partners where one has no EID/passport uploaded — `FLAG_08` for that person.

## Definition of done

- `app/kyc_compliance.py` exists, exports `analyse(extracted, today)`.
- `/generate-kyc` response carries the analysis dict.
- DOCX output is unchanged (no regressions for existing users).
- All four spot-checks above produce correct flags.
