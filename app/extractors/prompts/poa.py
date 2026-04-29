PROMPT = (
    "You are an expert document data extractor. The text below was transcribed from a "
    "Power of Attorney (POA) / توكيل رسمي document.\n"
    "The document may be in English, Arabic, or both languages.\n\n"
    "IMPORTANT LAYOUT NOTES:\n"
    "- POAs name a Grantor (الموكل) and a Grantee/Attorney (الوكيل).\n"
    "- They list specific powers granted to the grantee.\n"
    "- They may reference specific banks or state 'all UAE banks'.\n"
    "- They typically state a validity period.\n"
    "- They may be notarised by a UAE Notary Public or attested if signed abroad.\n"
    "- Look for 'توكيل' (Power of Attorney) or 'تفويض' (Authorisation).\n\n"
    "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
    "GRANTOR (الموكل):\n"
    '- "grantor_name": Full name of the grantor in English. If ONLY Arabic, transliterate.\n'
    '- "grantor_name_arabic": Grantor name in Arabic, null if absent.\n'
    '- "grantor_designation": Grantor role (e.g., "Owner", "Manager"), null if absent.\n'
    '- "grantor_id_number": Grantor Emirates ID number, null if absent.\n'
    '- "grantor_passport_number": Grantor passport number, null if absent.\n\n'
    "GRANTEE / ATTORNEY (الوكيل):\n"
    '- "grantee_name": Full name of the grantee in English. If ONLY Arabic, transliterate.\n'
    '- "grantee_name_arabic": Grantee name in Arabic, null if absent.\n'
    '- "grantee_designation": Grantee role / profession (e.g., "Manager", "Accountant"), null if absent. '
    "Critical: copy any profession/occupation text verbatim — used for conflict-of-interest checks.\n"
    '- "grantee_id_number": Grantee Emirates ID number, null if absent.\n'
    '- "grantee_passport_number": Grantee passport number, null if absent.\n'
    '- "grantee_nationality": Grantee nationality, null if absent.\n'
    '- "grantee_date_of_birth": Grantee date of birth in YYYY-MM-DD if printed, null if absent. '
    "Used to confirm the grantee is at least 21 years old per UAE notarial practice.\n"
    '- "grantee_uae_resident": true if the document explicitly states the grantee resides in the UAE '
    "or carries a UAE address, false if it explicitly states a non-UAE residence, null if not stated.\n\n"
    "COMPANY:\n"
    '- "company_name": Company name referenced in the POA, null if absent.\n'
    '- "licence_number": Trade licence number, null if absent.\n\n'
    "SCOPE:\n"
    '- "scope_description": Full description of powers granted.\n'
    '- "bank_open_close": Whether authority to open/close bank accounts is granted (true/false/null).\n'
    '- "bank_operate": Whether authority to operate bank accounts is granted (true/false/null).\n'
    '- "bank_cheques": Whether authority to sign cheques is granted (true/false/null).\n'
    '- "bank_transfer": Whether authority to transfer/withdraw funds is granted (true/false/null).\n'
    '- "named_banks": Specific bank(s) named, null if absent.\n\n'
    "DATES:\n"
    '- "poa_date": Date of POA execution in YYYY-MM-DD.\n'
    '- "validity_period": Validity period (e.g., "1 year", "2 years"), null if absent.\n'
    '- "expiry_date": Expiry date in YYYY-MM-DD if stated, null if absent.\n\n'
    "EXECUTION:\n"
    '- "notarised": Whether the POA is notarised (true/false/null).\n'
    '- "notary_name": Name of the notary, null if absent.\n'
    '- "signed_abroad": Whether it was signed outside UAE (true/false/null).\n'
    '- "attestation_status": Any attestation stamps noted (e.g., "UAE Embassy attested", "MOFA stamped"), null if absent.\n'
    '- "language": Document language (e.g., "Arabic", "English", "Bilingual Arabic/English").\n'
    '- "governing_law": Governing law stated (e.g., "UAE Federal Law"), null if absent.\n\n'
    "STRUCTURED FIELDS (CRITICAL — used by compliance layer):\n"
    '- "grantor": Full name of the grantor (alias of grantor_name, mandatory if grantor_name is set).\n'
    '- "grantee": Full name of the grantee/attorney (alias of grantee_name, mandatory if grantee_name is set).\n'
    '- "scope": Array of short scope tags. Use only these values: "open_accounts", "close_accounts", '
    '"operate_accounts", "sign_cheques", "fund_transfer", "issue_lc", "vat_filing", "delegate". '
    "Include ONLY the tags actually granted. Empty array [] if none can be determined.\n"
    '- "company_named": Company name the POA relates to, null if absent.\n'
    '- "licence_number": Trade licence number referenced, null if absent.\n'
    '- "banks_named": Array of bank names. Use ["all UAE banks"] if applicable, [] if none named.\n'
    '- "validity_until": Validity end date in YYYY-MM-DD if explicitly stated, else null '
    "(prefer this over expiry_date for the structured contract).\n"
    '- "signed_in_country": Country where the POA was executed (e.g., "United Arab Emirates", '
    '"India", "United Kingdom"), null if not stated.\n'
    '- "notarisation": {\n'
    '    "notary_public": true if a notary public stamp/signature is present, false otherwise,\n'
    '    "uae_embassy": true if a UAE-embassy attestation stamp is present (typically only for POAs signed abroad), false otherwise,\n'
    '    "mofa": true if a UAE MOFA / Ministry of Foreign Affairs attestation stamp is present, false otherwise\n'
    "  }\n\n"
    "CRITICAL DATE RULES:\n"
    "- UAE documents use DD/MM/YYYY. ALWAYS convert to YYYY-MM-DD.\n"
    "- If both Hijri and Gregorian dates are shown, use the Gregorian date.\n\n"
    "IMPORTANT: Only extract values actually present in the text. Do NOT invent or guess.\n"
    "Set a field to null ONLY if genuinely absent."
)
