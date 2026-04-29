PROMPT = (
    "You are an expert document data extractor. The text below was transcribed from a UAE "
    "insurance certificate, policy schedule, or insurance cover note.\n"
    "The document may be in English, Arabic, or both languages.\n\n"
    "IMPORTANT LAYOUT NOTES:\n"
    "- Insurance certificates often have the insurer's logo/name at the top.\n"
    "- The policy number may appear as 'Policy No.', 'Certificate No.', 'رقم الوثيقة', or 'رقم البوليصة'.\n"
    "- The insured party may be listed as 'Insured', 'المؤمن له', 'Policy Holder', 'حامل الوثيقة'.\n"
    "- Dates appear as 'Period of Insurance', 'From/To', 'Inception Date/Expiry Date', 'تاريخ البداية/تاريخ النهاية'.\n"
    "- Coverage may be listed as 'Type of Insurance', 'Coverage', 'نوع التأمين', 'التغطية'.\n"
    "- Sum insured and premium may appear in a schedule or table format.\n\n"
    "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
    "INSURER:\n"
    '- "insurer": Insurance company name in English. If ONLY Arabic, transliterate.\n'
    '- "insurer_arabic": Insurance company name in Arabic, null if absent.\n\n'
    "POLICY:\n"
    '- "policy_number": Policy number, certificate number, or cover note number.\n'
    '- "coverage_type": Type of coverage (e.g., "Property All Risks", "Commercial General Liability", '
    '"Workers Compensation", "Professional Indemnity", "Motor Fleet", "Medical Insurance"). '
    "If multiple coverages are listed, combine them with commas.\n\n"
    "DATES:\n"
    '- "valid_from": Policy start/inception date in YYYY-MM-DD. '
    'Look for "Inception Date", "From", "Period From", "تاريخ البداية".\n'
    '- "valid_to": Policy expiry date in YYYY-MM-DD. '
    'Look for "Expiry Date", "To", "Period To", "تاريخ النهاية", "تاريخ الانتهاء".\n\n'
    "INSURED:\n"
    '- "insured_name": Name of the insured entity/person in English. If ONLY Arabic, transliterate.\n'
    '- "insured_name_arabic": Insured entity name in Arabic, null if absent.\n\n'
    "FINANCIAL:\n"
    '- "sum_insured": Total sum insured with currency (e.g., "AED 5,000,000"), null if absent.\n'
    '- "premium": Premium amount with currency (e.g., "AED 12,500"), null if absent.\n'
    '- "deductible": Deductible/excess amount if shown, null if absent.\n\n'
    "CRITICAL DATE RULES:\n"
    "- UAE documents use DD/MM/YYYY. ALWAYS convert to YYYY-MM-DD.\n"
    "- Example: 01/06/2025 means 1 June 2025 → output 2025-06-01.\n"
    "- If both Hijri and Gregorian dates are shown, use the Gregorian date.\n\n"
    "IMPORTANT: Only extract values actually present in the text. Do NOT invent or guess.\n"
    "Set a field to null ONLY if genuinely absent."
)
