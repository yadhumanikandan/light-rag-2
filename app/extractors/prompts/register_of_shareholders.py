from app.extractors._attestation import ATTESTATION_BLOCK

PROMPT = (
    "You are an expert document data extractor. The text below was transcribed from a "
    "Register of Shareholders / Members issued by a corporate registry.\n\n"
    "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
    "COMPANY:\n"
    '- "company_name": Company whose register this is.\n'
    '- "registration_number": Company registration number, null if absent.\n'
    '- "jurisdiction": Country / free-zone of incorporation, null if absent.\n'
    '- "date_of_issue": Date the register was issued / certified, in YYYY-MM-DD, null if absent.\n\n'
    "SHAREHOLDERS:\n"
    '- "shareholders": Array of shareholder objects. For EACH shareholder listed:\n'
    '  - "name": Full name as printed.\n'
    '  - "nationality": Nationality / country of origin if printed, null otherwise.\n'
    '  - "share_pct": Shareholding percentage (e.g., "100%", "51%"), null if absent.\n'
    '  - "person_or_entity_id": Passport number, ID number, or corporate registration number — '
    "whichever identifies this shareholder, null if absent.\n\n"
    + ATTESTATION_BLOCK +
    "CRITICAL: Extract ALL shareholders listed, not just the first one.\n"
    "IMPORTANT: Only extract values actually present in the text. Do NOT invent or guess.\n"
    "Set a field to null ONLY if genuinely absent."
)
