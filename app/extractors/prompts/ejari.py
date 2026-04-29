PROMPT = (
    "You are an expert document data extractor. The text below was transcribed from an Ejari "
    "tenancy contract registration certificate.\n"
    "Ejari documents may be in English, Arabic, or both languages.\n\n"
    "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
    "CONTRACT:\n"
    '- "ejari_number": Ejari registration number (رقم إيجاري).\n'
    '- "start_date": Contract start date in YYYY-MM-DD.\n'
    '- "expiry_date": Contract end date in YYYY-MM-DD. Look for "Contract End Date" / "تاريخ انتهاء العقد".\n'
    '- "registration_date": Ejari registration date in YYYY-MM-DD, null if absent.\n'
    '- "registered_by": Agent or real estate company that registered the Ejari, null if absent.\n\n'
    "FINANCIAL:\n"
    '- "annual_rent": Annual rent amount (e.g., "AED 21,000"), null if absent.\n'
    '- "security_deposit": Security deposit amount (e.g., "AED 0"), null if absent.\n'
    '- "ejari_fees_paid": Ejari fees with receipt number if shown, null if absent.\n\n'
    "TENANT:\n"
    '- "tenant_name": Tenant name in English. If ONLY Arabic (المستأجر), transliterate.\n'
    '- "tenant_name_arabic": Tenant name in Arabic, null if absent.\n\n'
    "PROPERTY:\n"
    '- "building_name": Building name.\n'
    '- "unit_number": Unit/apartment number.\n'
    '- "area": Area/district name.\n'
    '- "unit_type": Type (e.g., "Office", "Apartment", "مكتب"), null if absent.\n'
    '- "size": Unit size, null if absent.\n'
    '- "plot_number": Plot number, null if absent.\n'
    '- "land_dm_parcel_id": Land DM or Parcel ID, null if absent.\n'
    '- "makani_number": Makani number, null if absent.\n\n'
    "LICENCE REFERENCE:\n"
    '- "licence_number": Trade licence number referenced on the Ejari, null if absent.\n'
    '- "licence_issuer": Trade licence issuing authority, null if absent.\n\n'
    "LANDLORD:\n"
    '- "landlord_name": Landlord/owner English name. If ONLY Arabic (المالك), transliterate.\n'
    '- "landlord_name_arabic": Landlord name in Arabic, null if absent.\n'
    '- "landlord_owner_number": Owner number, null if absent.\n'
    '- "landlord_nationality": Landlord nationality, null if absent.\n\n'
    "PROPERTY MANAGER:\n"
    '- "property_manager": Property manager name, null if absent.\n'
    '- "property_manager_email": Property manager email, null if absent.\n\n'
    "CRITICAL DATE RULES:\n"
    "- UAE documents use DD/MM/YYYY. ALWAYS convert to YYYY-MM-DD.\n"
    "- If both Hijri and Gregorian dates are shown, use the Gregorian date.\n\n"
    "Set a field to null ONLY if genuinely absent."
)
