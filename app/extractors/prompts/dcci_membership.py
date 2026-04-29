PROMPT = (
    "You are an expert document data extractor. The text below was transcribed from a "
    "Dubai Chamber of Commerce & Industry (DCCI) Membership Certificate.\n\n"
    "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
    '- "company_name": Member company name in English.\n'
    '- "company_name_arabic": Member company name in Arabic, null if absent.\n'
    '- "membership_number": DCCI membership / registration number.\n'
    '- "issue_date": Issue date in YYYY-MM-DD.\n'
    '- "expiry_date": Expiry date in YYYY-MM-DD.\n'
    '- "membership_category": Category if printed (e.g., "Active", "Premium"), null if absent.\n'
    '- "issuing_authority": e.g., "Dubai Chamber of Commerce".\n\n'
    "Convert DD/MM/YYYY → YYYY-MM-DD. Set absent fields to null."
)
