PROMPT = (
    "You are an expert document data extractor. The text below was transcribed from a passport.\n"
    "The passport may contain text in English, Arabic, French, or multiple languages.\n\n"
    "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
    "NAME:\n"
    '- "holder_name": Full name in ENGLISH. Look for "Surname"/"Family Name"/"Last Name" and '
    '"Given Names"/"First Name" labels. Arabic passports may show الاسم/اللقب with English text beside them. '
    "Combine surname + given names into one readable full name. "
    "If ONLY Arabic name is visible, transliterate it to English. "
    "MRZ fallback: P<COUNTRY_SURNAME<<GIVEN<NAMES — replace << with space, < with space, trim extra spaces.\n"
    '- "given_names": Given names / first names ONLY (without surname), in English. '
    "From the MRZ this is everything after the << separator on line 1.\n"
    '- "surname": Surname / family name ONLY, in English. From the MRZ this is the part '
    "before the << separator on line 1 (after the 3-letter country code).\n"
    '- "father_name": Father\'s name in English if printed (some passports show "Father\'s Name", '
    '"Name of Father", "اسم الأب", or include it on the address/family page). '
    "If ONLY Arabic, transliterate. Set to null if genuinely absent.\n"
    '- "holder_name_arabic": Full name in Arabic script if present, otherwise null.\n\n'
    "PASSPORT:\n"
    '- "passport_number": Alphanumeric passport number (typically 6-9 characters). '
    'Look for "Passport No." / "رقم الجواز". MRZ: line 2, first 9 chars before the check digit.\n\n'
    "DATES:\n"
    '- "expiry_date": Expiry date in YYYY-MM-DD. Look for "Date of Expiry" / "تاريخ الانتهاء". '
    "MRZ: line 2, positions 22-27 (YYMMDD) — prefix 20 for years < 70.\n"
    '- "date_of_birth": Date of birth in YYYY-MM-DD. Look for "Date of Birth" / "تاريخ الميلاد". '
    "MRZ: line 2, positions 14-19 (YYMMDD).\n"
    '- "issue_date": Issue date in YYYY-MM-DD. Look for "Date of Issue" / "تاريخ الإصدار".\n\n'
    "OTHER:\n"
    '- "nationality": Nationality as printed in English (e.g., "UNITED ARAB EMIRATES", "INDIAN").\n'
    '- "gender": "Male" or "Female". Look for "Sex" label or MRZ position 21 (M=Male, F=Female).\n'
    '- "place_of_birth": Place of birth as printed.\n'
    '- "issuing_country": Country that issued the passport.\n'
    '- "issuing_authority": Issuing authority if printed, otherwise null.\n\n'
    "CRITICAL DATE RULES:\n"
    "- UAE/GCC documents commonly use DD/MM/YYYY. ALWAYS convert to YYYY-MM-DD.\n"
    "- Example: 15/03/2028 means 15 March 2028 → output 2028-03-15.\n"
    "- MRZ dates are YYMMDD — 280315 means 2028-03-15.\n"
    "- If both Hijri (هجري) and Gregorian dates are shown, use the Gregorian date.\n"
    "- If ONLY a Hijri date is present, convert it to Gregorian.\n\n"
    "IMPORTANT: Only extract values actually present in the text. Do NOT invent or guess.\n"
    "Set a field to null if genuinely absent."
)
