"""
Two-step Claude Sonnet extraction for KYC document generation.

Step 1 — OCR: Transcribe all visible text (English + Arabic) from document images.
         Framed as plain transcription to avoid safety filter refusals on identity documents.

Step 2 — Parse: Extract structured JSON fields from the transcription text only.
         No image in this step, so vision-based safety checks don't apply.

Supports multi-page PDFs — each page is rendered at 300 DPI and sent as a separate image.
"""

import base64
import json
import re

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from app.config import ANTHROPIC_API_KEY, OPENAI_API_KEY

client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
_openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)

_MODEL = "claude-sonnet-4-6"
_OCR_MODEL = "gpt-5"


# Shared attestation block — emitted on every corporate-shareholder doc extraction.
# Detect each stage by visible stamp / seal / signature, NOT inferred. If a stage is
# illegible or ambiguous, set its boolean to null (unknown).
_ATTESTATION_BLOCK = (
    "ATTESTATION (CRITICAL — detect by visible stamp/seal/signature, do NOT infer):\n"
    '- "attestation": {\n'
    '    "language": "english" | "arabic" | "<other>" — primary language of the document body,\n'
    '    "stage1_translation":  {"present": true|false|null, "translator": "<name>" | null} '
    "— certified-translation cover page or translator stamp,\n"
    '    "stage2_home_country": {"notary": true|false|null, "mfa": true|false|null, '
    '"apostille": true|false|null} — home-country notary seal, foreign-MFA stamp, or Apostille certificate,\n'
    '    "stage3_uae_embassy":  {"present": true|false|null, "location": "<embassy city>" | null} '
    "— UAE embassy attestation stamp on the document,\n"
    '    "stage4_uae_mofa":     {"present": true|false|null} '
    "— UAE Ministry of Foreign Affairs attestation stamp.\n"
    "  }\n"
    "Rule: present=true only if a clear matching stamp/seal/signature is visible. "
    "Set present=false only if the stage would normally be on this page and is clearly absent. "
    "If illegible or unclear, set present=null.\n\n"
)


def _strip_json_fences(text: str) -> str:
    """Remove markdown ```json ... ``` fences sometimes wrapping JSON responses."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text

# ── Step 1: bilingual OCR prompt ────────────────────────────────────────────
_OCR_SYSTEM = (
    "You are a highly accurate multilingual OCR assistant. "
    "Transcribe EVERY piece of text visible in the image(s) exactly as it appears:\n"
    "- All English text: names, labels, numbers, dates, codes, addresses\n"
    "- All Arabic text (الأسماء، التواريخ، العناوين): transcribe Arabic characters exactly as printed\n"
    "- All machine-readable zones (MRZ): transcribe character by character including < symbols\n"
    "- All stamps, watermarks, headers, footers, margin text\n"
    "- All numbers: dates, monetary amounts, phone numbers, reference numbers, ID numbers\n\n"
    "Rules:\n"
    "1. Transcribe EXACTLY as printed — do not correct spelling or grammar\n"
    "2. Preserve line-by-line layout structure\n"
    "3. For bilingual text, transcribe BOTH languages on the same line if they appear together\n"
    "4. Do NOT skip, summarize, redact, or omit ANY text\n"
    "5. Output raw transcription only — no commentary or formatting\n"
    "6. If multiple pages are provided, separate with '--- PAGE BREAK ---'"
)

# ── Step 2: field extraction prompts (bilingual Arabic + English aware) ─────
_EXTRACT_PROMPTS = {
    "passport": (
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
    ),
    "emirates_id": (
        "You are an expert document data extractor. The text below was transcribed from a UAE Emirates ID card.\n"
        "The card is bilingual: Arabic text on the right side, English on the left side.\n\n"
        "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
        "NAME:\n"
        '- "holder_name": ENGLISH full name. Look for the "Name:" label on the front face. '
        "If ONLY Arabic name (الاسم) is visible, transliterate it to English. "
        "MRZ fallback: name on the second MRZ line after the ID number check digit.\n"
        '- "holder_name_arabic": Full name in Arabic script if present, otherwise null.\n\n'
        "ID:\n"
        '- "id_number": 15-digit UAE ID number in format 784-XXXX-XXXXXXX-X. '
        "Look for number starting with 784 on the front face. "
        "MRZ: line starting with IDARE, positions 6-20 are the ID digits.\n"
        '- "card_number": Card number if shown separately from the ID number, otherwise null.\n\n'
        "DATES:\n"
        '- "expiry_date": in YYYY-MM-DD. Look for "Expiry Date:" / "تاريخ الانتهاء". '
        "MRZ line 2: positions 22-27 (YYMMDD), prefix 20.\n"
        '- "date_of_birth": in YYYY-MM-DD. Look for "Date of Birth:" / "تاريخ الميلاد". '
        "MRZ line 2: positions 1-6 (YYMMDD).\n\n"
        "OTHER:\n"
        '- "nationality": As printed in English (e.g., "UNITED ARAB EMIRATES").\n'
        '- "gender": "Male" or "Female". From printed text or MRZ position 8 (M=Male, F=Female).\n'
        '- "issuing_authority": e.g., "Federal Authority for Identity and Citizenship" if shown.\n'
        '- "issuing_place": Issuing place / city if printed (e.g., "Dubai", "Abu Dhabi"), else null.\n'
        '- "occupation": Occupation / profession if printed on the card '
        '(some EIDs show "Profession" / "المهنة"), else null.\n'
        '- "employer": Sponsor / employer name as printed on the card '
        '(some EIDs show "Sponsor" / "الكفيل"), else null. Do NOT infer from other documents.\n\n'
        "CRITICAL DATE RULES:\n"
        "- UAE documents use DD/MM/YYYY. ALWAYS convert to YYYY-MM-DD.\n"
        "- Example: 31/07/2028 → 2028-07-31.\n\n"
        "Set a field to null ONLY if genuinely absent."
    ),
    "trade_license": (
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
    ),
    "ejari": (
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
    ),
    "moa": (
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
    ),
    "insurance": (
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
    ),
    "residence_visa": (
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
    ),
    "vat_certificate": (
        "You are an expert document data extractor. The text below was transcribed from a UAE "
        "VAT Registration Certificate issued by the Federal Tax Authority (FTA / الهيئة الاتحادية للضرائب).\n"
        "The certificate is bilingual (Arabic + English).\n\n"
        "IMPORTANT LAYOUT NOTES:\n"
        "- The FTA header appears at the top: 'Federal Tax Authority / الهيئة الاتحادية للضرائب'.\n"
        "- The document title is: 'Tax Registration Certificate / شهادة التسجيل الضريبي'.\n"
        "- The TRN (Tax Registration Number / رقم التسجيل الضريبي) is a 15-digit number, "
        "often starting with '100' (e.g., 100123456789012). It is the most important identifier.\n"
        "- The registrant name appears as 'Registrant Name / اسم المسجل' in both languages.\n"
        "- The effective date is when VAT registration becomes active.\n"
        "- The address appears as 'Address / العنوان'.\n"
        "- VAT certificates do NOT have an expiry date — registration is ongoing.\n\n"
        "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
        "REGISTRANT:\n"
        '- "company_name": Registered entity name in English. Look for "Registrant Name" / "اسم المسجل". '
        "If ONLY Arabic, transliterate.\n"
        '- "company_name_arabic": Registered entity name in Arabic, null if absent.\n\n'
        "TAX DETAILS:\n"
        '- "trn": Tax Registration Number (15-digit number starting with 100). '
        'Look for "TRN" / "رقم التسجيل الضريبي". This is the most critical field.\n'
        '- "effective_date": VAT registration effective date in YYYY-MM-DD. '
        'Look for "Effective Registration Date" / "تاريخ سريان التسجيل".\n'
        '- "return_period": VAT return filing period (e.g., "Quarterly", "Monthly"). '
        'Look for "Tax Period" / "الفترة الضريبية".\n'
        '- "registration_type": Registration type (e.g., "Mandatory", "Voluntary"). '
        'Look for "Registration Type" / "نوع التسجيل".\n\n'
        "ADDRESS:\n"
        '- "registered_address": Full registered address in English. Look for "Address" / "العنوان". '
        "Combine all address lines into one string.\n"
        '- "registered_address_arabic": Full address in Arabic, null if absent.\n\n'
        "CRITICAL DATE RULES:\n"
        "- UAE documents use DD/MM/YYYY. ALWAYS convert to YYYY-MM-DD.\n"
        "- Example: 01/01/2018 means 1 January 2018 → output 2018-01-01.\n\n"
        "IMPORTANT: Only extract values actually present in the text. Do NOT invent or guess.\n"
        "Set a field to null ONLY if genuinely absent."
    ),
    "board_resolution": (
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
    ),
    "poa": (
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
    ),
    "partners_annex": (
        "You are an expert document data extractor. The text below was transcribed from a UAE "
        "Partners Annex, Schedule of Partners, or Shareholder Register attached to a Trade Licence or MOA.\n"
        "The document is typically bilingual (Arabic + English).\n\n"
        "IMPORTANT LAYOUT NOTES:\n"
        "- The Partners Annex lists all shareholders/partners of the company.\n"
        "- Each partner entry typically shows: name, nationality, person number, shareholding %.\n"
        "- Partners may be NATURAL PERSONS (individuals) or CORPORATE ENTITIES (companies).\n"
        "- Corporate entities are identified by legal suffixes like LLC, Ltd, PJSC, Sarl, GmbH, DMCC, etc.\n"
        "- Look for 'ملحق الشركاء' (Partners Annex) or 'جدول المساهمين' (Shareholder Schedule).\n"
        "- The company name and licence number usually appear at the top.\n\n"
        "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
        "COMPANY:\n"
        '- "company_name": Company name in English. If ONLY Arabic, transliterate.\n'
        '- "company_name_arabic": Company name in Arabic, null if absent.\n'
        '- "licence_number": Trade licence number, null if absent.\n\n'
        "PARTNERS:\n"
        '- "partners": An array of partner objects. For EACH partner/shareholder listed, extract:\n'
        '  - "name": Full name in English. If ONLY Arabic, transliterate.\n'
        '  - "name_arabic": Name in Arabic, null if absent.\n'
        '  - "nationality": Nationality as printed.\n'
        '  - "person_number": Person No. (رقم الشخص), null if absent. '
        "An Emirates-ID-shaped person number identifies a natural person.\n"
        '  - "share_percentage": Shareholding percentage (e.g., "51%", "49%", "100%").\n'
        '  - "share_value": Share value in AED if stated, null if absent.\n'
        '  - "role": Role (e.g., "Partner", "Owner", "Shareholder"), null if absent.\n'
        '  - "is_corporate": true if the entry uses LLC / L.L.C / Ltd / Limited / PJSC / DMCC / '
        "Sarl / GmbH / Inc / Corp / Co. / Company / Establishment terminology in the name OR "
        "lacks a personal Emirates-ID-shaped person number; otherwise false.\n"
        '  - "jurisdiction": For corporate partners, the country / free-zone of incorporation '
        "(e.g., \"DMCC\", \"BVI\", \"Cayman Islands\"). Null if absent or natural person.\n"
        '  - "registration_number": Corporate registration / incorporation number if listed, '
        "null otherwise (only meaningful for corporate partners).\n\n"
        "CRITICAL RULES:\n"
        "- Extract ALL partners listed, not just the first one.\n"
        "- Carefully identify whether each partner is a natural person or a corporate entity.\n"
        "- Corporate entities will have legal suffixes (LLC, Ltd, PJSC, Sarl, GmbH, DMCC, Inc, etc.).\n"
        "- If shareholding percentages are shown, extract them exactly as printed.\n\n"
        "IMPORTANT: Only extract values actually present in the text. Do NOT invent or guess.\n"
        "Set a field to null ONLY if genuinely absent."
    ),
    "certificate_of_incorporation": (
        "You are an expert document data extractor. The text below was transcribed from a "
        "Certificate of Incorporation issued by a corporate registry (UAE or foreign).\n\n"
        "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
        "COMPANY:\n"
        '- "company_name": Registered company name as printed.\n'
        '- "registration_number": Company / incorporation registration number.\n'
        '- "jurisdiction": Country and / or free-zone of incorporation '
        '(e.g., "British Virgin Islands", "DMCC", "Cayman Islands").\n'
        '- "date_of_incorporation": Date of incorporation in YYYY-MM-DD.\n'
        '- "issuing_authority": Issuing registrar / authority name.\n\n'
        + _ATTESTATION_BLOCK +
        "CRITICAL DATE RULES:\n"
        "- Convert any DD/MM/YYYY date to YYYY-MM-DD.\n"
        "- If both Hijri and Gregorian dates are shown, use Gregorian.\n\n"
        "IMPORTANT: Only extract values actually present in the text. Do NOT invent or guess.\n"
        "Set a field to null ONLY if genuinely absent."
    ),
    "register_of_shareholders": (
        "You are an expert document data extractor. The text below was transcribed from a "
        "Register of Shareholders / Members issued by a corporate registry.\n\n"
        "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
        "COMPANY:\n"
        '- "company_name": Company whose register this is.\n'
        '- "registration_number": Company registration number, null if absent.\n'
        '- "jurisdiction": Country / free-zone of incorporation, null if absent.\n'
        '- "date_of_issue": Date the register was issued / certified, in YYYY-MM-DD, null if absent.\n\n'
        "SHAREHOLDERS:\n"
        '- "shareholders": Array of shareholder objects. For EACH shareholder listed:\n'
        '  - "name": Full name as printed.\n'
        '  - "nationality": Nationality / country of origin if printed, null otherwise.\n'
        '  - "share_pct": Shareholding percentage (e.g., "100%", "51%"), null if absent.\n'
        '  - "person_or_entity_id": Passport number, ID number, or corporate registration number — '
        "whichever identifies this shareholder, null if absent.\n\n"
        + _ATTESTATION_BLOCK +
        "CRITICAL: Extract ALL shareholders listed, not just the first one.\n"
        "IMPORTANT: Only extract values actually present in the text. Do NOT invent or guess.\n"
        "Set a field to null ONLY if genuinely absent."
    ),
    "register_of_directors": (
        "You are an expert document data extractor. The text below was transcribed from a "
        "Register of Directors / Officers issued by a corporate registry.\n\n"
        "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
        "COMPANY:\n"
        '- "company_name": Company whose register this is.\n'
        '- "registration_number": Company registration number, null if absent.\n'
        '- "jurisdiction": Country / free-zone of incorporation, null if absent.\n'
        '- "date_of_issue": Date the register was issued / certified, in YYYY-MM-DD, null if absent.\n\n'
        "DIRECTORS:\n"
        '- "directors": Array of director objects. For EACH director listed:\n'
        '  - "name": Full name as printed.\n'
        '  - "nationality": Nationality if printed, null otherwise.\n'
        '  - "appointment_date": Appointment date in YYYY-MM-DD, null if absent.\n\n'
        + _ATTESTATION_BLOCK +
        "CRITICAL: Extract ALL directors listed.\n"
        "IMPORTANT: Only extract values actually present in the text. Do NOT invent or guess.\n"
        "Set a field to null ONLY if genuinely absent."
    ),
    "free_zone_license": (
        "You are an expert document data extractor. The text below was transcribed from a "
        "UAE Free Zone Licence (DMCC, IFZA, RAKEZ, UAQ FTZ, JAFZA, ADGM, DIFC, etc.).\n\n"
        "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
        "COMPANY:\n"
        '- "company_name": English company name. If ONLY Arabic, transliterate.\n'
        '- "company_name_arabic": Arabic company name, null if absent.\n'
        '- "license_number": Licence number.\n'
        '- "free_zone": Issuing free-zone authority (e.g., "DMCC", "IFZA", "RAKEZ").\n'
        '- "legal_form": Legal structure (e.g., "FZ-LLC", "Branch", "Establishment").\n'
        '- "branch_status": "branch" if the licence is a branch of a foreign entity, "main" otherwise.\n\n'
        "DATES:\n"
        '- "issue_date": Issue date in YYYY-MM-DD.\n'
        '- "expiry_date": Expiry date in YYYY-MM-DD.\n\n'
        "ADDRESS / CONTACT:\n"
        '- "registered_address": Full registered address.\n'
        '- "phone": Phone, null if absent.\n'
        '- "email": Email, null if absent.\n\n'
        "MANAGER / OWNER:\n"
        '- "manager_name": Manager English name.\n'
        '- "owner_name": Owner / shareholder English name.\n'
        '- "owner_nationality": Owner nationality, null if absent.\n\n'
        "ACTIVITY:\n"
        '- "business_activity": Primary activity in English.\n'
        '- "activity_scope": Full activity description, null if absent.\n\n'
        "CRITICAL DATE RULES: convert DD/MM/YYYY to YYYY-MM-DD. Set fields to null when absent."
    ),
    "dcci_membership": (
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
    ),
    "renewal_receipt": (
        "You are an expert document data extractor. The text below was transcribed from a UAE "
        "trade-licence renewal receipt or fee-payment voucher (DED, Trakhees, free-zone authority).\n\n"
        "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
        '- "company_name": Company name on the receipt.\n'
        '- "license_number": Licence number referenced on the receipt, null if absent.\n'
        '- "receipt_number": Receipt or transaction number.\n'
        '- "payment_date": Payment date in YYYY-MM-DD.\n'
        '- "fee_amount": Fee amount with currency (e.g., "AED 12,910").\n'
        '- "procedure_type": Procedure (e.g., "Trade Licence Renewal", "New Licence", "Amendment").\n'
        '- "issuing_authority": Issuing department (e.g., "Dubai Economy", "DMCC").\n'
        '- "payer_name": Payer name if printed, null if absent.\n\n'
        "Convert DD/MM/YYYY → YYYY-MM-DD. Set absent fields to null."
    ),
    "audited_financials": (
        "You are an expert document data extractor. The text below was transcribed from "
        "audited financial statements / auditor's report (UAE or foreign).\n\n"
        "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
        '- "company_name": Audited entity name.\n'
        '- "auditor_name": Audit firm name.\n'
        '- "auditor_registration": Auditor registration / licence number, null if absent.\n'
        '- "financial_year_end": Reporting period end date in YYYY-MM-DD.\n'
        '- "report_date": Date the auditor signed the report in YYYY-MM-DD.\n'
        '- "audit_opinion": Opinion type (e.g., "Unqualified", "Qualified", "Adverse", '
        '"Disclaimer of Opinion"), null if absent.\n'
        '- "currency": Currency of the statements (e.g., "AED", "USD"), null if absent.\n'
        '- "total_assets": Total assets value as a string (with currency), null if absent.\n'
        '- "total_revenue": Total revenue / turnover value as a string, null if absent.\n'
        '- "net_profit": Net profit / loss value as a string, null if absent.\n'
        '- "fiscal_years_covered": Array of YYYY year strings covered by the report '
        '(e.g., ["2024", "2023"]).\n\n'
        "Convert DD/MM/YYYY → YYYY-MM-DD. Set absent fields to null."
    ),
    "ubo_declaration": (
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
    ),
    "specimen_signatures": (
        "You are an expert document data extractor. The text below was transcribed from a "
        "Specimen Signatures certificate / signature card naming the persons authorised to "
        "sign on behalf of a corporate shareholder or the UAE entity.\n\n"
        "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
        '- "company_name": Issuing entity name.\n'
        '- "registration_number": Company registration / licence number, null if absent.\n'
        '- "issue_date": Date the certificate was issued in YYYY-MM-DD.\n'
        '- "issuing_authority": Authority that certified the signatures (notary, registrar, '
        "corporate secretary), null if absent.\n"
        '- "signatories": Array of signatory objects. For each named person:\n'
        '    - "name": Full name in English.\n'
        '    - "designation": Role / title (e.g., "Director", "Manager", "Authorised Signatory").\n'
        '    - "passport_number": Passport number, null if absent.\n'
        '    - "id_number": Emirates ID number, null if absent.\n'
        '    - "signing_mode": Signing mode for this person (e.g., "Solely", "Jointly with another"), '
        "null if absent.\n\n"
        "Set absent fields to null."
    ),
    "certificate_of_good_standing": (
        "You are an expert document data extractor. The text below was transcribed from a "
        "Certificate of Good Standing / Incumbency certificate issued by a corporate registry.\n\n"
        "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
        "COMPANY:\n"
        '- "company_name": Company name as printed.\n'
        '- "status": Company status as stated (e.g., "Good Standing", "Active", "In Good Standing").\n'
        '- "date_of_issue": Date the certificate was issued in YYYY-MM-DD.\n'
        '- "issuing_authority": Issuing registrar / authority name.\n'
        '- "registration_number": Company registration number, null if absent.\n\n'
        + _ATTESTATION_BLOCK +
        "IMPORTANT: Only extract values actually present in the text. Do NOT invent or guess.\n"
        "Set a field to null ONLY if genuinely absent."
    ),
}


def _bytes_to_base64_images(file_bytes: bytes, filename: str) -> list[tuple[str, str]]:
    """Return list of (base64_data, media_type) tuples. PDFs yield one tuple per page (up to 10 pages at 300 DPI)."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf":
        try:
            import fitz
        except ImportError:
            raise RuntimeError("Install pymupdf: pip install pymupdf")
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        images = []
        max_pages = min(len(doc), 10)
        for i in range(max_pages):
            pix = doc[i].get_pixmap(dpi=300)
            img_bytes = pix.tobytes("png")
            images.append((base64.b64encode(img_bytes).decode(), "image/png"))
        doc.close()
        return images
    media_map = {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "webp": "image/webp",
    }
    media_type = media_map.get(ext, "image/jpeg")
    return [(base64.b64encode(file_bytes).decode(), media_type)]


async def extract_for_kyc(files: list[tuple[bytes, str]], doc_type: str) -> dict:
    """
    Two-step extraction:
      1. OCR — transcribe all visible text (English + Arabic) from document images.
      2. Parse — extract structured JSON fields from the transcription.
    Supports multi-page PDFs (up to 10 pages at 300 DPI) and multiple uploaded files
    (e.g. Emirates ID front + back as two separate images).

    Args:
        files:    list of (file_bytes, filename) tuples — one per uploaded file for this doc type.
        doc_type: document type key (e.g. "emirates_id").
    """
    if doc_type not in _EXTRACT_PROMPTS:
        return {"error": f"Unknown document type '{doc_type}'."}

    images = []
    for file_bytes, filename in files:
        images.extend(_bytes_to_base64_images(file_bytes, filename))

    # ── Step 1: transcribe all pages (bilingual OCR via GPT-5 vision) ────────
    content_blocks = []
    for b64, media_type in images:
        content_blocks.append({
            "type": "image_url",
            "image_url": {"url": f"data:{media_type};base64,{b64}", "detail": "high"},
        })
    content_blocks.append({
        "type": "text",
        "text": "Transcribe all text visible in this document. Include ALL Arabic and English text, every number, date, and code.",
    })

    ocr_resp = await _openai_client.chat.completions.create(
        model=_OCR_MODEL,
        messages=[
            {"role": "system", "content": _OCR_SYSTEM},
            {"role": "user", "content": content_blocks},
        ],
        reasoning_effort="minimal",
    )
    transcription = (ocr_resp.choices[0].message.content or "").strip()
    print(f"[OCR transcription for {doc_type}]:\n{transcription[:800]}", flush=True)

    if not transcription:
        return {"error": f"Could not read text from the {doc_type.replace('_', ' ')} image."}

    # Detect safety refusals — don't proceed to extraction if the model refused
    _REFUSAL_PHRASES = (
        "i'm sorry", "i cannot", "i can't", "i am unable", "i'm unable",
        "unable to transcribe", "cannot transcribe", "sorry, i", "as an ai",
        "i'm not able", "i am not able",
    )
    if any(p in transcription.lower() for p in _REFUSAL_PHRASES):
        print(f"[OCR] Detected refusal for {doc_type}. Transcription: {transcription[:300]}", flush=True)
        return {"error": f"Could not read text from the {doc_type.replace('_', ' ')} image. Please upload a clearer scan."}

    # ── Step 2: extract structured fields from the transcription ─────────────
    extract_resp = await client.messages.create(
        model=_MODEL,
        system=_EXTRACT_PROMPTS[doc_type] + "\n\nRespond with ONLY a valid JSON object, no other text.",
        messages=[{"role": "user", "content": transcription}],
        max_tokens=2500,
        temperature=0,
    )

    raw = _strip_json_fences(extract_resp.content[0].text)
    print(f"[EXTRACT raw for {doc_type}]:\n{raw[:500]}", flush=True)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": f"Could not parse {doc_type.replace('_', ' ')} data."}


# ── Document classification (for bulk-upload UI) ───────────────────────────────

_CLASSIFY_TYPES = {
    "passport", "emirates_id", "residence_visa", "trade_license", "ejari",
    "moa", "insurance", "vat_certificate", "board_resolution", "poa",
    "partners_annex", "certificate_of_incorporation", "register_of_shareholders",
    "register_of_directors", "certificate_of_good_standing",
    "free_zone_license", "dcci_membership", "renewal_receipt",
    "audited_financials", "ubo_declaration", "specimen_signatures",
    "unknown",
}

_CLASSIFY_SYSTEM = (
    "You are a UAE KYC document classifier. Identify the document type from its header, "
    "issuing-authority logo/seal, layout and key phrases. Return ONLY a JSON object:\n"
    '{"doc_type": "<allowed value>", "confidence": "high|medium|low", "reason": "<≤15 words, cite the visible cue>"}\n\n'
    "ALLOWED VALUES with discriminating cues (English + common Arabic header):\n"
    "- passport — passport booklet page; MRZ at bottom (P< / two-line `<<<`); 'PASSPORT / جواز سفر'; "
    "any country (UAE, India, Pakistan, Bangladesh, UK, etc.). NOT a visa sticker.\n"
    "- emirates_id — UAE Emirates ID card (polycarbonate). Front: photo + 'United Arab Emirates / "
    "الهوية' + 784-XXXX-XXXXXXX-X. Back: card-holder signature + occupation + chip; treat front AND "
    "back BOTH as emirates_id.\n"
    "- residence_visa — visa sticker INSIDE a passport page or e-visa PDF; 'Residence / إقامة', "
    "'U.I.D. No', 'Visa File No', sponsor name. NOT the EID card.\n"
    "- trade_license — UAE mainland trade licence: 'Trade Licence / الرخصة التجارية' issued by DED "
    "(Department of Economic Development / Economic Department) of an emirate. Has Licence No., "
    "legal form, partners list. NOT a free-zone authority.\n"
    "- free_zone_license — UAE free-zone licence: header names a free-zone authority — DMCC, IFZA, "
    "RAKEZ, RAK ICC, JAFZA, DAFZA, ADGM, DIFC, SHAMS, Meydan, UAQ FTZ, Dubai South, KIZAD, "
    "Fujairah Creative City, twofour54, Masdar. NOT DED.\n"
    "- ejari — Dubai Ejari tenancy contract (RERA-registered). Header 'Ejari / إيجاري' or 'Tenancy "
    "Contract' with Ejari contract number / Dubai Land Department / RERA logo. Tawtheeq (Abu Dhabi) "
    "and other emirate tenancy contracts also map here.\n"
    "- moa — Memorandum / Articles of Association. Long contract document, 'Memorandum of "
    "Association / عقد التأسيس', clauses about capital, share split, partners, manager. "
    "Bilingual columns common. NOT a one-page resolution.\n"
    "- board_resolution — short 'Resolution' document: 'Board Resolution', 'Shareholders' Resolution', "
    "'RESOLVED THAT…' clauses. Authorises a specific act (open bank account, appoint signatory). "
    "Usually 1-3 pages. NOT a full MOA.\n"
    "- poa — 'Power of Attorney / توكيل'. Grantor appoints a named attorney-in-fact. Often "
    "notarised by UAE notary public or foreign notary + embassy. NOT a board resolution.\n"
    "- partners_annex — Partners' Annex / Shareholders Appendix attached to the MOA, listing "
    "partners with shares. Header often 'Annex' or 'ملحق الشركاء'.\n"
    "- insurance — insurance policy / certificate; insurer logo (Oman Insurance, AXA, Orient, etc.); "
    "'Policy No.', 'Sum Insured', cover period.\n"
    "- vat_certificate — single-page UAE VAT registration certificate from Federal Tax Authority "
    "(FTA / الهيئة الاتحادية للضرائب). Shows TRN (15-digit) + effective date. NOT a tax invoice.\n"
    "- certificate_of_incorporation — Certificate of Incorporation issued at company formation by a "
    "registrar (Companies House UK, ADGM Registrar, BVI FSC, etc.). States the company is duly "
    "incorporated. One-page.\n"
    "- certificate_of_good_standing — Certificate of Good Standing / Incumbency / Continued "
    "Existence. Issued AFTER incorporation to confirm current active status. NOT the incorporation "
    "certificate.\n"
    "- register_of_shareholders — formal Register of Shareholders / Members maintained by company "
    "secretary; columnar table of shareholders, share class, count, dates of allotment/transfer.\n"
    "- register_of_directors — Register of Directors / Officers; columnar table of directors with "
    "appointment / resignation dates.\n"
    "- dcci_membership — Dubai Chamber of Commerce & Industry membership certificate ONLY. "
    "Specifically the DCCI logo + 'Member of Dubai Chamber'.\n"
    "- renewal_receipt — trade-licence renewal RECEIPT / payment voucher / fee invoice. Short, "
    "shows fees paid + receipt number. NOT the licence itself.\n"
    "- audited_financials — Audited Financial Statements / Auditor's Report. Multi-page; auditor's "
    "opinion + Balance Sheet + Profit & Loss + signature of audit firm.\n"
    "- ubo_declaration — Ultimate Beneficial Owner declaration / Real-Beneficiary register / "
    "'UBO Form'. Lists natural persons owning ≥25%.\n"
    "- specimen_signatures — Specimen Signatures certificate / signature card; sample signatures of "
    "authorised signatories, often attested.\n"
    "- unknown — only if no discriminator above is visible.\n\n"
    "DISAMBIGUATION RULES (apply in order):\n"
    "1. If the issuer is a UAE free-zone authority → free_zone_license, NEVER trade_license.\n"
    "2. If the page is a visa sticker inside a passport booklet → residence_visa, NOT passport.\n"
    "3. The back of an Emirates ID card → emirates_id (same type as the front).\n"
    "4. 'Memorandum of Association' (multi-clause contract) → moa; one-page 'Resolution' → "
    "board_resolution; 'Power of Attorney' → poa — these are NOT interchangeable.\n"
    "5. 'Certificate of Incorporation' (formed-on date) ≠ 'Good Standing' (currently-active).\n"
    "6. Tenancy contract from any emirate → ejari (Dubai Ejari is the canonical case).\n\n"
    "CONFIDENCE:\n"
    "- high  — issuer logo / mandatory header phrase clearly visible.\n"
    "- medium — layout matches but logo/header partially visible.\n"
    "- low   — guessing from weak cues.\n\n"
    "Output: ONLY the JSON object, no markdown fences, no commentary."
)


def _classify_image(file_bytes: bytes, filename: str) -> tuple[str, str] | None:
    """Render a small first-page image for the classifier only.
    PDFs → page 1 at 150 DPI (vs 300 DPI used by extraction) for ~4× smaller payload.
    Raster files are passed through unchanged — already small."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf":
        try:
            import fitz
        except ImportError:
            raise RuntimeError("Install pymupdf: pip install pymupdf")
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        if len(doc) == 0:
            doc.close()
            return None
        pix = doc[0].get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        doc.close()
        return base64.b64encode(img_bytes).decode(), "image/png"
    media_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
    media_type = media_map.get(ext, "image/jpeg")
    return base64.b64encode(file_bytes).decode(), media_type


async def classify_document(file_bytes: bytes, filename: str) -> dict:
    """Classify a single document into one of the supported KYC doc types.
    Uses GPT-5 vision on the first page only — low detail + minimal reasoning + short cap."""
    try:
        img = _classify_image(file_bytes, filename)
    except Exception as exc:
        return {"doc_type": "unknown", "confidence": "low", "reason": f"read error: {exc}"}
    if img is None:
        return {"doc_type": "unknown", "confidence": "low", "reason": "empty file"}

    b64, media_type = img
    try:
        resp = await _openai_client.chat.completions.create(
            model=_OCR_MODEL,
            messages=[
                {"role": "system", "content": _CLASSIFY_SYSTEM},
                {"role": "user", "content": [
                    {"type": "image_url",
                     "image_url": {"url": f"data:{media_type};base64,{b64}", "detail": "low"}},
                    {"type": "text", "text": "Classify this document. Return JSON only."},
                ]},
            ],
            reasoning_effort="minimal",
            max_completion_tokens=120,
            response_format={"type": "json_object"},
        )
        text = _strip_json_fences((resp.choices[0].message.content or "").strip())
        result = json.loads(text)
        dt = result.get("doc_type", "unknown")
        if dt not in _CLASSIFY_TYPES:
            dt = "unknown"
        conf = result.get("confidence", "medium")
        if conf not in ("high", "medium", "low"):
            conf = "medium"
        return {
            "doc_type": dt,
            "confidence": conf,
            "reason": (result.get("reason") or "")[:160],
        }
    except json.JSONDecodeError:
        return {"doc_type": "unknown", "confidence": "low", "reason": "parse error"}
    except Exception as exc:
        return {"doc_type": "unknown", "confidence": "low", "reason": f"classify error: {exc}"}
