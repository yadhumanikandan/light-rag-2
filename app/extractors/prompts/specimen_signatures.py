PROMPT = (
    "You are an expert document data extractor. The text below was transcribed from a "
    "Specimen Signatures certificate / signature card naming the persons authorised to "
    "sign on behalf of a corporate shareholder or the UAE entity.\n\n"
    "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
    '- "company_name": Issuing entity name.\n'
    '- "registration_number": Company registration / licence number, null if absent.\n'
    '- "issue_date": Date the certificate was issued in YYYY-MM-DD.\n'
    '- "issuing_authority": Authority that certified the signatures (notary, registrar, '
    "corporate secretary), null if absent.\n"
    '- "signatories": Array of signatory objects. For each named person:\n'
    '    - "name": Full name in English.\n'
    '    - "designation": Role / title (e.g., "Director", "Manager", "Authorised Signatory").\n'
    '    - "passport_number": Passport number, null if absent.\n'
    '    - "id_number": Emirates ID number, null if absent.\n'
    '    - "signing_mode": Signing mode for this person (e.g., "Solely", "Jointly with another"), '
    "null if absent.\n\n"
    "Set absent fields to null."
)
