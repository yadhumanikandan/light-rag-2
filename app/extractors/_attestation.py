# Shared attestation block — emitted on every corporate-shareholder doc extraction.
# Detect each stage by visible stamp / seal / signature, NOT inferred. If a stage is
# illegible or ambiguous, set its boolean to null (unknown).
ATTESTATION_BLOCK = (
    "ATTESTATION (CRITICAL — detect by visible stamp/seal/signature, do NOT infer):\n"
    '- "attestation": {\n'
    '    "language": "english" | "arabic" | "<other>" — primary language of the document body,\n'
    '    "stage1_translation":  {"present": true|false|null, "translator": "<name>" | null} '
    "— certified-translation cover page or translator stamp,\n"
    '    "stage2_home_country": {"notary": true|false|null, "mfa": true|false|null, '
    '"apostille": true|false|null} — home-country notary seal, foreign-MFA stamp, or Apostille certificate,\n'
    '    "stage3_uae_embassy":  {"present": true|false|null, "location": "<embassy city>" | null} '
    "— UAE embassy attestation stamp on the document,\n"
    '    "stage4_uae_mofa":     {"present": true|false|null} '
    "— UAE Ministry of Foreign Affairs attestation stamp.\n"
    "  }\n"
    "Rule: present=true only if a clear matching stamp/seal/signature is visible. "
    "Set present=false only if the stage would normally be on this page and is clearly absent. "
    "If illegible or unclear, set present=null.\n\n"
)
