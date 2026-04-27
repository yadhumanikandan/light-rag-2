# NAAS v4.0 KYC Upgrade — Phase Plans

Reference spec: `../upgrade.md` (NAAS Master Prompt v4.0, April 2026).

Phases are sequential. Each plan is self-contained — read top-to-bottom, follow the build order, finish with the verification + definition-of-done checklists.

| Phase | File | Owner area | Depends on |
|-------|------|-----------|------------|
| 1 | [phase1_compliance_layer.md](phase1_compliance_layer.md) | New `app/kyc_compliance.py` — pure-logic analysis (validity, cross-checks, MOA authority, presence, shareholders, attestation, flags). No DOCX or extractor changes. | — |
| 2 | [phase2_extractor_upgrades.md](phase2_extractor_upgrades.md) | `app/kyc_extractor.py` prompts — structured banking-authority on MOA, corporate flag on Partners Annex, new corporate-shareholder doc types, attestation stamp detection. | Phase 1 |
| 3 | [phase3_docx_rewrite.md](phase3_docx_rewrite.md) | `app/kyc_generator.py` — 20-section spec layout, A–G checklist, flags block, header/footer/disclaimer. | Phase 1, 2 |
| 4 | [phase4_frontend.md](phase4_frontend.md) | `frontend/index.html` — compliance summary panel, new upload tiles, flag cards. | Phase 1, 2, 3 |

## Working tips

- After each phase, run the existing sample (`ASAAS AL TAMYUZ DATES & SWEETS L.L.C-Irshad/`) end-to-end before moving on.
- Keep DOCX output byte-stable through Phases 1–2 — Phase 3 is the first time it should change.
- Compliance flags are the integration contract between phases. Lock the flag schema in Phase 1, then Phase 3 / 4 just renders it.
