PROMPT = (
    "You are an expert document data extractor. The text below was transcribed from a UAE "
    "Residence Visa / Entry Permit / Residence Permit (تصريح إقامة / إذن إقامة).\n"
    "The visa is bilingual (Arabic on the right, English on the left) and is typically "
    "a sticker inside the passport or an electronic visa printout.\n\n"
    "IMPORTANT LAYOUT NOTES:\n"
    "- UAE residence visas have a header: 'UNITED ARAB EMIRATES / الإمارات العربية المتحدة'.\n"
    "- The visa type appears at the top: 'RESIDENCE VISA / إقامة' or 'ENTRY PERMIT / إذن دخول'.\n"
    "- Arabic labels appear on the right side, English labels on the left.\n"
    "- The name usually appears as 'Name / الاسم' — may be in English, Arabic, or both.\n"
    "- 'الكفيل' means Sponsor/Employer. 'المهنة' means Profession/Occupation.\n"
    "- The File Number (رقم الملف) is the main tracking number for immigration.\n"
    "- UID/Unified Number (الرقم الموحد) may also appear.\n"
    "- The visa number is a separate reference (often near the top or bottom).\n"
    "- Passport number appears as 'Passport No. / رقم الجواز'.\n"
    "- ID number (784-…) may appear as 'ID No. / رقم الهوية'.\n\n"
    "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
    "NAME:\n"
    '- "holder_name": Full name in ENGLISH. Look for "Name:" / "الاسم". '
    "If ONLY Arabic name is visible, transliterate it to English.\n"
    '- "holder_name_arabic": Full name in Arabic script if present, otherwise null.\n\n'
    "IDENTIFIERS:\n"
    '- "id_number": UAE ID number (15-digit, starts with 784-XXXX-XXXXXXX-X), null if absent.\n'
    '- "passport_number": Passport number referenced on the visa. Look for "Passport No." / "رقم الجواز".\n'
    '- "file_number": File number (رقم الملف). This is the main immigration file reference.\n'
    '- "visa_number": Visa or entry permit number. Often printed near the top of the visa.\n'
    '- "uid_number": Unified Number (الرقم الموحد), null if absent.\n\n'
    "EMPLOYMENT:\n"
    '- "profession": Profession/occupation in English. Look for "Profession" / "المهنة". '
    "If ONLY Arabic, transliterate (e.g., مدير → Manager, مهندس → Engineer, محاسب → Accountant).\n"
    '- "profession_arabic": Profession in Arabic, null if absent.\n'
    '- "employer": Sponsor/employer name in English. Look for "Sponsor" / "الكفيل". '
    "If ONLY Arabic, transliterate.\n"
    '- "employer_arabic": Sponsor/employer name in Arabic, null if absent.\n\n'
    "DATES:\n"
    '- "issue_date": Issue date in YYYY-MM-DD. Look for "Date of Issue" / "تاريخ الإصدار".\n'
    '- "expiry_date": Expiry date in YYYY-MM-DD. Look for "Date of Expiry" / "تاريخ الانتهاء" / "صالح لغاية".\n\n'
    "OTHER:\n"
    '- "place_of_issue": Issuing authority or city (e.g., "Dubai" / "Abu Dhabi"), null if absent.\n'
    '- "nationality": Nationality as printed. Look for "Nationality" / "الجنسية".\n'
    '- "gender": "Male" or "Female" if printed, null if absent.\n'
    '- "date_of_birth": Date of birth in YYYY-MM-DD if printed, null if absent.\n\n'
    "CRITICAL DATE RULES:\n"
    "- UAE documents use DD/MM/YYYY. ALWAYS convert to YYYY-MM-DD.\n"
    "- Example: 15/09/2026 means 15 September 2026 → output 2026-09-15.\n"
    "- If both Hijri (هجري) and Gregorian dates are shown, use the Gregorian date.\n"
    "- If ONLY a Hijri date is present, convert it to Gregorian.\n\n"
    "IMPORTANT: Only extract values actually present in the text. Do NOT invent or guess.\n"
    "Set a field to null ONLY if genuinely absent."
)
