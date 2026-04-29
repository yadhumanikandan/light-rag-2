PROMPT = (
    "You are an expert document data extractor. The text below was transcribed from "
    "an Ultimate Beneficial Owner (UBO) declaration / Real-Beneficiary register filing "
    "(per UAE Cabinet Decision 58/2020 and equivalent foreign rules).\n\n"
    "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
    "COMPANY:\n"
    '- "company_name": Declaring entity name.\n'
    '- "license_number": Trade licence / registration number, null if absent.\n'
    '- "declaration_date": Declaration date in YYYY-MM-DD.\n'
    '- "declared_by": Name and role of the person signing the declaration, null if absent.\n\n'
    "BENEFICIAL OWNERS:\n"
    '- "ubos": Array of UBO objects. For EACH UBO listed:\n'
    '    - "name": Full name in English.\n'
    '    - "name_arabic": Full name in Arabic, null if absent.\n'
    '    - "nationality": Nationality.\n'
    '    - "passport_number": Passport number, null if absent.\n'
    '    - "id_number": Emirates ID number, null if absent.\n'
    '    - "date_of_birth": DOB in YYYY-MM-DD, null if absent.\n'
    '    - "place_of_birth": Place of birth, null if absent.\n'
    '    - "share_percentage": Beneficial-ownership percentage (e.g., "100%", "25%").\n'
    '    - "control_basis": Basis of control (e.g., "Direct ownership", "Voting rights"), '
    "null if absent.\n"
    '    - "address": Residential address, null if absent.\n\n'
    "Set absent fields to null. Convert DD/MM/YYYY → YYYY-MM-DD."
)
