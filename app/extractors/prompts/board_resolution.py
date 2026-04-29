PROMPT = (
    "You are an expert document data extractor. The text below was transcribed from a UAE "
    "Board Resolution, Owner's Resolution, or Shareholders' Resolution.\n"
    "The document may be in English, Arabic, or both languages.\n\n"
    "IMPORTANT LAYOUT NOTES:\n"
    "- Board Resolutions typically begin with the company name and licence number.\n"
    "- They name the authorised signatory and list specific banking powers granted.\n"
    "- They may name specific bank(s) or state 'all UAE banks'.\n"
    "- They are usually signed by the owner/all directors and may carry a company stamp.\n"
    "- They may be notarised by a UAE Notary Public.\n"
    "- Look for 'قرار مجلس الإدارة' (Board Resolution) or 'قرار المالك' (Owner's Resolution).\n\n"
    "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
    "COMPANY:\n"
    '- "company_name": Company name in English. If ONLY Arabic, transliterate.\n'
    '- "company_name_arabic": Company name in Arabic, null if absent.\n'
    '- "licence_number": Trade licence number referenced in the resolution, null if absent.\n\n'
    "RESOLUTION DETAILS:\n"
    '- "resolution_date": Date of resolution in YYYY-MM-DD.\n'
    '- "resolution_type": Type (e.g., "Board Resolution", "Owner\'s Resolution", "Shareholders\' Resolution").\n'
    '- "effective_date": Effective date if different from resolution date, null if absent.\n'
    '- "validity_period": Validity period (e.g., "Until further notice", "1 year", "2 years"), null if absent.\n'
    '- "expiry_date": Expiry date in YYYY-MM-DD if stated, null if absent.\n\n'
    "SIGNATORY:\n"
    '- "signatory_name": Full name of the authorised signatory in English. If ONLY Arabic, transliterate.\n'
    '- "signatory_name_arabic": Signatory name in Arabic, null if absent.\n'
    '- "signatory_designation": Designation/role (e.g., "Manager", "Director", "Owner"), null if absent.\n'
    '- "signing_mode": Signing mode (e.g., "Individual", "Joint — two signatories required"), null if absent.\n\n'
    "BANKING POWERS:\n"
    '- "bank_open_close": Whether authority to open/close bank accounts is granted (true/false/null).\n'
    '- "bank_operate": Whether authority to operate bank accounts is granted (true/false/null).\n'
    '- "bank_cheques": Whether authority to sign cheques is granted (true/false/null).\n'
    '- "bank_transfer": Whether authority to transfer/withdraw funds is granted (true/false/null).\n'
    '- "bank_sign_documents": Whether authority to sign all banking documents is granted (true/false/null).\n'
    '- "named_banks": Specific bank(s) named (e.g., "Emirates NBD", "all UAE banks"), null if absent.\n\n'
    "STRUCTURED POWERS (CRITICAL — same shape as MOA banking_authority.powers):\n"
    '- "powers_granted": {\n'
    '    "open_close_accounts": true|false|null,\n'
    '    "sign_cheques": true|false|null,\n'
    '    "transfer_withdraw_funds": true|false|null,\n'
    '    "delegate_via_poa": true|false|null\n'
    "  }\n"
    '- "validity_until": Validity end date in YYYY-MM-DD if explicitly stated, else null.\n'
    '- "banks_named": Array of bank names. Use ["all UAE banks"] if the resolution applies to all UAE banks. '
    "Empty array [] if none named.\n\n"
    "EXECUTION:\n"
    '- "signed_by": Name(s) of person(s) who signed the resolution, null if absent.\n'
    '- "notarised": Whether the resolution is notarised (true/false/null).\n'
    '- "notary_name": Name of the notary, null if absent.\n'
    '- "company_stamp": Whether a company stamp is present (true/false/null).\n\n'
    "CRITICAL DATE RULES:\n"
    "- UAE documents use DD/MM/YYYY. ALWAYS convert to YYYY-MM-DD.\n"
    "- If both Hijri and Gregorian dates are shown, use the Gregorian date.\n\n"
    "IMPORTANT: Only extract values actually present in the text. Do NOT invent or guess.\n"
    "Set a field to null ONLY if genuinely absent."
)
