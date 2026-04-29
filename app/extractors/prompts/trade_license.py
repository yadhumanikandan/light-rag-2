PROMPT = (
    "You are an expert document data extractor. The text below was transcribed from a UAE Trade License.\n"
    "Trade licenses are bilingual (Arabic + English), issued by DED or free zone authorities.\n\n"
    "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
    "COMPANY INFORMATION:\n"
    '- "company_name": English trade/company name. Look for "Trade Name" / "الاسم التجاري". '
    "If ONLY Arabic name is visible, transliterate it to English.\n"
    '- "company_name_arabic": Arabic company name if present, otherwise null.\n'
    '- "license_number": The license number (رقم الرخصة).\n'
    '- "register_number": Commercial/DED register number (رقم السجل), null if absent.\n'
    '- "dcci_membership_number": DCCI or Chamber of Commerce membership number, null if absent.\n'
    '- "legal_form": Legal structure (e.g., "One Person Limited Liability Company" / '
    '"شركة الشخص الواحد ذ.م.م"), null if absent.\n'
    '- "license_type": e.g., "Commercial Licence" / "رخصة تجارية", null if absent.\n'
    '- "licence_category": Issuing department or category, null if absent.\n\n'
    "DATES:\n"
    '- "expiry_date": License expiry in YYYY-MM-DD. Look for "Expiry Date" / "تاريخ الانتهاء".\n'
    '- "issue_date": Issue date in YYYY-MM-DD. Look for "Issue Date" / "تاريخ الإصدار".\n'
    '- "last_renewal_date": Last renewal date in YYYY-MM-DD, null if absent.\n\n'
    "FEES:\n"
    '- "last_renewal_fee": Renewal fee amount with receipt number if shown '
    '(e.g., "AED 12,910 Receipt No. 12345"), null if absent.\n\n'
    "BUSINESS ACTIVITY:\n"
    '- "business_activity": Primary activity name in English. If ONLY Arabic, transliterate.\n'
    '- "business_activity_arabic": Primary activity in Arabic, null if absent.\n'
    '- "activity_status": e.g., "Active" / "نشط", null if absent.\n'
    '- "activity_scope": Full activity description, null if absent.\n'
    '- "regulatory_approval": Any regulatory approval notes, null if absent.\n\n'
    "ADDRESS:\n"
    '- "registered_address": Complete address as one string.\n'
    '- "unit_number": Office/unit number extracted from address (e.g., "021-202"), null if absent.\n'
    '- "building_name": Building name from the address, null if absent.\n'
    '- "area": Area/district (e.g., "Hor Al Anz East" / "هور العنز شرق"), null if absent.\n'
    '- "parcel_id": Parcel ID or Land DM number, null if absent.\n'
    '- "makani_number": Makani number, null if absent.\n\n'
    "CONTACT:\n"
    '- "phone_fax": Phone or fax number, null if absent.\n'
    '- "mobile": Mobile number, null if absent.\n'
    '- "email": Email address, null if absent.\n'
    '- "issuing_authority": Issuing authority name.\n\n'
    "OWNER/PARTNER:\n"
    '- "owner_name": Owner/partner English name. If ONLY Arabic, transliterate.\n'
    '- "owner_name_arabic": Owner name in Arabic, null if absent.\n'
    '- "owner_nationality": Owner nationality.\n'
    '- "owner_share": Ownership percentage (e.g., "100%"), null if absent.\n'
    '- "owner_person_number": Person No. from the licence, null if absent.\n\n'
    "MANAGER:\n"
    '- "manager_name": Manager English name. If ONLY Arabic, transliterate.\n'
    '- "manager_name_arabic": Manager name in Arabic, null if absent.\n'
    '- "manager_nationality": Manager nationality, null if absent.\n'
    '- "manager_role": Role title (e.g., "Manager"), null if absent.\n'
    '- "manager_person_number": Manager Person No., null if absent.\n\n'
    "CRITICAL DATE RULES:\n"
    "- UAE documents use DD/MM/YYYY. ALWAYS convert to YYYY-MM-DD.\n"
    "- Example: 15/06/2025 → 2025-06-15.\n"
    "- If both Hijri and Gregorian dates are shown, use the Gregorian date.\n\n"
    "Set a field to null ONLY if genuinely absent from the transcription."
)
