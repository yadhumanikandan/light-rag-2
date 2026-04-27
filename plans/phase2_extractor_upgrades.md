# Phase 2 — Extractor Prompt Upgrades

Goal: extend `app/kyc_extractor.py` so MOA, Partners Annex, Board Resolution / POA, and corporate-shareholder document extractions emit the structured signals Phase 1's compliance layer needs. Also add new doc types for corporate-shareholder KYC.

Depends on: Phase 1 merged (compliance layer reads these new fields).

## Deliverables

1. New / extended fields on existing prompts (MOA, Partners Annex, Board Resolution, POA, EID, Visa).
2. New extractor entries for corporate-shareholder documents.
3. Updated `VALID_DOC_TYPES` in `app/main.py` and the `/generate-kyc` form fields.

## A. Extend existing prompts

### MOA (`_EXTRACT_PROMPTS["moa"]`)

Add structured banking-authority fields:

```
"banking_authority": {
  "explicitly_granted": true|false,
  "article_reference": "Article 7" | null,
  "powers": {
    "open_close_accounts": true|false|null,
    "sign_cheques": true|false|null,
    "transfer_withdraw_funds": true|false|null,
    "delegate_via_poa": true|false|null
  },
  "signing_mode": "individual"|"joint"|"unknown",
  "named_signatory": "<full name>" | null,
  "raw_clause": "<verbatim banking clause if present>"
}
```

Also add:
- `"moa_type": "original" | "amended" | "unknown"`
- `"governing_law": "<text>" | null`

Prompt instruction: extract verbatim banking-authority clause if present; do not paraphrase. If silent, set `explicitly_granted: false` and `raw_clause: null`.

### Partners Annex (`_EXTRACT_PROMPTS["partners_annex"]`)

For each partner, add:
- `"is_corporate": true|false` — true if entry uses LLC/Ltd/PJSC/DMCC/Sarl/GmbH/Inc/Corp/Co./Company/Establishment terminology OR lacks a personal Emirates ID-shaped person number.
- `"jurisdiction": "<country/zone>" | null` — only if corporate.
- `"registration_number": "..."` | null — corporate registration number if listed.

Keep existing `nationality`, `share_percentage`, `person_number`.

### Board Resolution (`_EXTRACT_PROMPTS["board_resolution"]`)

Add:
- `"powers_granted"`: same shape as MOA `powers`.
- `"validity_until": "YYYY-MM-DD" | null`
- `"effective_date": "YYYY-MM-DD" | null`
- `"banks_named": ["..."]` (list of named banks or `["all UAE banks"]`).
- `"notarised": true|false|null`

### POA (`_EXTRACT_PROMPTS["poa"]`)

Add:
- `"grantor": "<full name>"`
- `"grantee": "<full name>"`
- `"scope": ["open_accounts", "sign_cheques", "fund_transfer", ...]`
- `"company_named": "<company name>" | null`
- `"licence_number": "..." | null`
- `"banks_named": ["..."]`
- `"validity_until": "YYYY-MM-DD" | null`
- `"signed_in_country": "<country>" | null`
- `"notarisation": {"notary_public": bool, "uae_embassy": bool, "mofa": bool}`
- `"governing_law": "<text>" | null`

### EID and Residence Visa

Add `"employer": "<company name>" | null` to both (used for the employer-vs-TL cross-check in Phase 1). EID prompt should also extract `"occupation"` and `"issuing_place"`.

## B. New extractor entries (corporate shareholder docs)

Add four new keys to `_EXTRACT_PROMPTS`:

1. `"certificate_of_incorporation"` — fields: `company_name`, `registration_number`, `jurisdiction`, `date_of_incorporation`, `issuing_authority`, plus the attestation block (see C).
2. `"register_of_shareholders"` — list of `{name, nationality, share_pct, person_or_entity_id}`, plus attestation.
3. `"register_of_directors"` — list of `{name, nationality, appointment_date}`, plus attestation.
4. `"certificate_of_good_standing"` — `company_name`, `status`, `date_of_issue`, `issuing_authority`, plus attestation.

(Optional, lower priority: `"corporate_moa_aoa"`, `"audited_financial_statements"` — at least capture company_name + period covered + attestation block.)

## C. Attestation block (shared shape)

Every corporate-shareholder doc extraction returns:

```
"attestation": {
  "language": "english"|"arabic"|"<other>",
  "stage1_translation": {"present": bool, "translator": "<name>"|null},
  "stage2_home_country": {"notary": bool, "mfa": bool, "apostille": bool},
  "stage3_uae_embassy":  {"present": bool, "location": "<embassy>"|null},
  "stage4_uae_mofa":     {"present": bool}
}
```

Prompt rule: detect each stage by visible stamp/seal/signature, NOT inferred. If illegible, set the stage `"present": null` (unknown).

## D. Wire-up changes

### `app/main.py`

- Extend `VALID_DOC_TYPES` to include the four new corporate-shareholder doc keys.
- Extend `/generate-kyc` form parameters with optional `List[UploadFile]` for each.
- Add to the `uploads` dict.

### `app/kyc_generator.py`

- Update `identify_partners` to read the new `is_corporate` flag from partners_annex when present (falls back to current heuristic).
- No DOCX rendering changes here — Phase 3.

### `app/kyc_compliance.py` (Phase 1 module)

- Replace best-effort MOA parsing with reads from the new structured `moa.banking_authority` field.
- Populate `corporate_kyc[].provided` from the new corporate doc extractions.
- Populate `corporate_kyc[].attestation` from the new attestation block.
- Implement employer-vs-TL cross-check using new EID/Visa `employer` fields.

## Out of scope for Phase 2

- DOCX section rewrite (Phase 3).
- Frontend file-upload UI for new doc types (Phase 4).
- Multi-page concatenation logic (already handled).

## Verification

1. Run extraction against an MOA that contains an explicit banking clause — confirm `banking_authority.explicitly_granted == true` and `raw_clause` is verbatim.
2. Run against an MOA that is silent — confirm `explicitly_granted == false`.
3. Upload a Partners Annex with one LLC partner and one individual — confirm `is_corporate` is true for the LLC and false for the individual.
4. Upload a sample Certificate of Incorporation with an Apostille — confirm `attestation.stage2_home_country.apostille == true`.
5. Phase 1's compliance output now reflects: `moa_authority.sufficient` driven by structured field; `corporate_kyc.provided` non-empty; attestation gaps reported in flags.

## Definition of done

- All listed prompt changes shipped, JSON schemas honoured by the model on the sample documents.
- New doc types accepted by `/generate-kyc`.
- Phase 1 compliance flags now use structured fields rather than heuristics where applicable.
- Existing extractions for non-changed doc types remain backward-compatible.
