PROMPT = (
    "You are an expert document data extractor. The text below was transcribed from a UAE "
    "Memorandum of Association (MOA) / عقد تأسيس.\n"
    "MOA documents are typically bilingual (Arabic + English) and span multiple pages.\n"
    "The Arabic text appears alongside or above the English translation.\n\n"
    "IMPORTANT LAYOUT NOTES:\n"
    "- MOAs are structured as numbered articles (Article 1, Article 2… / المادة الأولى، المادة الثانية…).\n"
    "- The first page usually contains the contract number, notarisation details, and party information.\n"
    "- Capital and share information is typically in Articles 4-7.\n"
    "- Management/Manager appointment is typically in Articles 8-12.\n"
    "- Banking and signatory authority is typically in later articles (Articles 13-18).\n"
    "- Look for the word 'المدير' (Manager) and 'الشريك' (Partner/Shareholder).\n"
    "- Person numbers appear as 'Person No.' or 'رقم الشخص' near each individual's details.\n\n"
    "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
    "DOCUMENT:\n"
    '- "contract_number": MOA or contract number (رقم العقد). Often at the top of the first page.\n'
    '- "moa_date": Date of signing/notarisation in YYYY-MM-DD. Look for "بتاريخ" or "Date" near the top.\n\n'
    "COMPANY:\n"
    '- "company_name": English company name. Look for "Company Name" / "الاسم التجاري" / "اسم الشركة". If ONLY Arabic, transliterate.\n'
    '- "company_name_arabic": Arabic company name, null if absent.\n'
    '- "legal_form": Legal structure in English (e.g., "One Person Limited Liability Company" / "Sole Proprietorship LLC"). Look for "Legal Form" / "الشكل القانوني".\n'
    '- "legal_form_arabic": Legal form in Arabic, null if absent.\n'
    '- "company_duration": Duration of the company (e.g., "25 Years from registration auto-renewable"). Look for "مدة الشركة" / "Duration".\n'
    '- "financial_year": Financial year period (e.g., "January to December"). Look for "السنة المالية".\n'
    '- "disputes_jurisdiction": Jurisdiction for disputes (e.g., "Courts of Dubai"). Look for "الاختصاص القضائي".\n\n'
    "CAPITAL:\n"
    '- "share_capital": Total share capital with currency and status (e.g., "AED 300,000 Fully Paid"). Look for "رأس المال" / "Capital".\n'
    '- "shares_count": Number and nominal value of shares (e.g., "300 shares of AED 1,000 each"). Look for "عدد الحصص" / "Shares".\n'
    '- "capital_currency": Currency (e.g., "UAE Dirhams AED").\n'
    '- "capital_deposited": Whether capital has been deposited (e.g., "Yes — deposited with [bank name]").\n'
    '- "statutory_reserve": Reserve requirement details (e.g., "10% of net profits until reserve equals 50% of capital").\n\n'
    "SHAREHOLDERS / OWNERS (CRITICAL — extract ALL partners listed in the MOA):\n"
    "An MOA may list ONE or MULTIPLE shareholders/partners. Each Article naming partners "
    "may include a list/table with one row per partner. Look for sections titled "
    "'Partners' / 'الشركاء' / 'Shareholders' / 'المساهمين' / 'Capital Distribution' / "
    "'توزيع رأس المال'. Each partner typically has: name, nationality, person no., shares.\n"
    '- "shareholders": Array of partner objects. Extract EVERY partner/shareholder listed. '
    "For each partner, include:\n"
    '    - "name": English full name. If ONLY Arabic, transliterate.\n'
    '    - "name_arabic": Arabic full name, null if absent.\n'
    '    - "nationality": Nationality as printed.\n'
    '    - "person_number": Person No. (رقم الشخص), null if absent.\n'
    '    - "shares": Share details including number, value, and percentage '
    '(e.g., "25 Shares AED 50,000 25%"). If only a percentage is shown, use that.\n'
    '    - "share_percentage": Just the percentage as a string (e.g., "25%", "100%"), null if absent.\n'
    '    - "liability": Liability description, null if absent.\n'
    '    - "residence": City and country of residence, null if absent.\n'
    '    - "role": Role description (e.g., "Partner", "Shareholder", "Owner"), null if absent.\n'
    "BACKWARDS-COMPAT FIELDS (set these to the FIRST shareholder for legacy consumers):\n"
    '- "owner_name": Same as shareholders[0].name.\n'
    '- "owner_name_arabic": Same as shareholders[0].name_arabic.\n'
    '- "owner_nationality": Same as shareholders[0].nationality.\n'
    '- "owner_person_number": Same as shareholders[0].person_number.\n'
    '- "owner_shares": Same as shareholders[0].shares.\n'
    '- "owner_liability": Same as shareholders[0].liability.\n'
    '- "owner_residence": Same as shareholders[0].residence.\n\n'
    "MANAGERS (CRITICAL — extract ALL managers listed in the MOA):\n"
    "An MOA may name ONE or MULTIPLE managers. Look for sections titled "
    "'Manager' / 'المدير' / 'Managers' / 'المدراء' / 'Management' / 'الإدارة'.\n"
    '- "managers": Array of manager objects. Extract EVERY manager listed. '
    "For each manager, include:\n"
    '    - "name": English full name. If ONLY Arabic, transliterate.\n'
    '    - "name_arabic": Arabic full name, null if absent.\n'
    '    - "nationality": Nationality, null if absent.\n'
    '    - "residence": City and country, null if absent.\n'
    '    - "pobox": P.O. Box, null if absent.\n'
    '    - "person_number": Person No., null if absent.\n'
    '    - "role": Role title (e.g., "Manager" / "مدير"), null if absent.\n'
    '    - "appointment_term": Appointment duration, null if absent.\n'
    "BACKWARDS-COMPAT FIELDS (set these to the FIRST manager for legacy consumers):\n"
    '- "manager_name": Same as managers[0].name.\n'
    '- "manager_name_arabic": Same as managers[0].name_arabic.\n'
    '- "manager_nationality": Same as managers[0].nationality.\n'
    '- "manager_residence": Same as managers[0].residence.\n'
    '- "manager_pobox": Same as managers[0].pobox.\n'
    '- "manager_person_number": Same as managers[0].person_number.\n'
    '- "manager_role": Same as managers[0].role.\n'
    '- "manager_appointment_term": Same as managers[0].appointment_term.\n\n'
    "SIGNING AUTHORITY:\n"
    '- "signing_authority": Full signing authority description. Look for "صلاحية التوقيع" / "Signing Authority".\n'
    '- "authorised_signatory": Name and role of authorised signatory.\n'
    '- "signing_mode": Signing mode (e.g., "INDIVIDUAL sole signatory" / "JOINT — two signatories required").\n\n'
    "BANKING AUTHORITY (free-text — keep these for backward compat):\n"
    "For each of the following, extract the full authority text including who is authorised:\n"
    '- "bank_open_close": Authority to open/close bank accounts.\n'
    '- "bank_operate": Authority to operate bank accounts.\n'
    '- "bank_cheques": Authority to sign cheques.\n'
    '- "bank_transfer": Authority to transfer/withdraw funds.\n'
    '- "bank_tenders": Authority to sign tenders and contracts.\n'
    '- "bank_lc": Authority to issue letters of credit / guarantees.\n'
    '- "bank_vat": Authority for VAT/FTA returns and tax registrations.\n'
    '- "bank_delegate": Authority to delegate powers to third parties.\n\n'
    "STRUCTURED BANKING AUTHORITY (CRITICAL):\n"
    "Also emit a structured object summarising the banking authority. Detect by looking for "
    "an article that explicitly grants powers to open / operate bank accounts, sign cheques, "
    "transfer funds, or delegate via POA.\n"
    '- "banking_authority": {\n'
    '    "explicitly_granted": true if the MOA contains an explicit banking-authority clause, '
    "false if the MOA is silent on banking,\n"
    '    "article_reference": e.g. "Article 7" if numbered, otherwise null,\n'
    '    "powers": {\n'
    '      "open_close_accounts": true|false|null,\n'
    '      "sign_cheques": true|false|null,\n'
    '      "transfer_withdraw_funds": true|false|null,\n'
    '      "delegate_via_poa": true|false|null\n'
    "    },\n"
    '    "signing_mode": "individual" (sole signatory) | "joint" (two or more required) | "unknown",\n'
    '    "named_signatory": full name of the person granted these powers, else null,\n'
    '    "raw_clause": VERBATIM text of the banking clause if present — do NOT paraphrase. '
    "Null if the MOA is silent.\n"
    "  }\n\n"
    "Rule: if the MOA does not contain a banking clause, set explicitly_granted=false and "
    "raw_clause=null. Do NOT invent powers.\n\n"
    "MOA META:\n"
    '- "moa_type": "original" | "amended" | "unknown" — "amended" if the document mentions '
    '"amendment", "addendum", "تعديل", or shows it modifies a prior MOA.\n'
    '- "governing_law": text of the governing-law clause if present, else null '
    '(e.g. "UAE Federal Law", "Laws of the Emirate of Dubai").\n\n'
    "CRITICAL DATE RULES:\n"
    "- UAE documents use DD/MM/YYYY. ALWAYS convert to YYYY-MM-DD.\n"
    "- If both Hijri (هجري) and Gregorian dates are shown, use the Gregorian date.\n"
    "- If ONLY a Hijri date is present, convert it to Gregorian.\n\n"
    "IMPORTANT: Only extract values actually present in the text. Do NOT invent or guess.\n"
    "Set a field to null ONLY if genuinely absent from the transcription."
)
