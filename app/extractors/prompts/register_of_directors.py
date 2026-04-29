from app.extractors._attestation import ATTESTATION_BLOCK

PROMPT = (
    "You are an expert document data extractor. The text below was transcribed from a "
    "Register of Directors / Officers issued by a corporate registry.\n\n"
    "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
    "COMPANY:\n"
    '- "company_name": Company whose register this is.\n'
    '- "registration_number": Company registration number, null if absent.\n'
    '- "jurisdiction": Country / free-zone of incorporation, null if absent.\n'
    '- "date_of_issue": Date the register was issued / certified, in YYYY-MM-DD, null if absent.\n\n'
    "DIRECTORS:\n"
    '- "directors": Array of director objects. For EACH director listed:\n'
    '  - "name": Full name as printed.\n'
    '  - "nationality": Nationality if printed, null otherwise.\n'
    '  - "appointment_date": Appointment date in YYYY-MM-DD, null if absent.\n\n'
    + ATTESTATION_BLOCK +
    "CRITICAL: Extract ALL directors listed.\n"
    "IMPORTANT: Only extract values actually present in the text. Do NOT invent or guess.\n"
    "Set a field to null ONLY if genuinely absent."
)
