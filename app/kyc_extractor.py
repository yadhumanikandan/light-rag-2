"""
Two-step GPT-4.1 extraction for KYC document generation.

Step 1 — OCR: Transcribe all visible text (English + Arabic) from document images.
         Framed as plain transcription to avoid safety filter refusals on identity documents.

Step 2 — Parse: Extract structured JSON fields from the transcription text only.
         No image in this step, so vision-based safety checks don't apply.

Supports multi-page PDFs — each page is rendered at 300 DPI and sent as a separate image.
"""

import base64
import json

from openai import AsyncOpenAI
from app.config import OPENAI_API_KEY

client = AsyncOpenAI(api_key=OPENAI_API_KEY)

_MODEL = "gpt-4.1"

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
        '- "issuing_authority": e.g., "Federal Authority for Identity and Citizenship" if shown.\n\n'
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
        "OWNER/SHAREHOLDER:\n"
        '- "owner_name": English full name of the sole shareholder or primary partner. If ONLY Arabic, transliterate.\n'
        '- "owner_name_arabic": Arabic full name, null if absent.\n'
        '- "owner_nationality": Nationality as printed.\n'
        '- "owner_person_number": Person No. (رقم الشخص), null if absent.\n'
        '- "owner_shares": Share details including number, value, and percentage (e.g., "300 Shares AED 300,000 100%").\n'
        '- "owner_liability": Liability description (e.g., "Limited to the value of shares held").\n'
        '- "owner_residence": City and country of residence.\n\n'
        "MANAGER:\n"
        '- "manager_name": English full name. The manager may be the same person as the owner. If ONLY Arabic, transliterate.\n'
        '- "manager_name_arabic": Arabic full name, null if absent.\n'
        '- "manager_nationality": Nationality.\n'
        '- "manager_residence": City and country.\n'
        '- "manager_pobox": P.O. Box, null if absent.\n'
        '- "manager_person_number": Person No., null if absent.\n'
        '- "manager_role": Role title (e.g., "Manager" / "مدير").\n'
        '- "manager_appointment_term": Appointment duration (e.g., "For the duration of the company" / "Renewable annually").\n\n'
        "SIGNING AUTHORITY:\n"
        '- "signing_authority": Full signing authority description. Look for "صلاحية التوقيع" / "Signing Authority".\n'
        '- "authorised_signatory": Name and role of authorised signatory.\n'
        '- "signing_mode": Signing mode (e.g., "INDIVIDUAL sole signatory" / "JOINT — two signatories required").\n\n'
        "BANKING AUTHORITY:\n"
        "For each of the following, extract the full authority text including who is authorised:\n"
        '- "bank_open_close": Authority to open/close bank accounts.\n'
        '- "bank_operate": Authority to operate bank accounts.\n'
        '- "bank_cheques": Authority to sign cheques.\n'
        '- "bank_transfer": Authority to transfer/withdraw funds.\n'
        '- "bank_tenders": Authority to sign tenders and contracts.\n'
        '- "bank_lc": Authority to issue letters of credit / guarantees.\n'
        '- "bank_vat": Authority for VAT/FTA returns and tax registrations.\n'
        '- "bank_delegate": Authority to delegate powers to third parties.\n\n'
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


async def extract_for_kyc(file_bytes: bytes, filename: str, doc_type: str) -> dict:
    """
    Two-step extraction:
      1. OCR — transcribe all visible text (English + Arabic) from document images.
      2. Parse — extract structured JSON fields from the transcription.
    Supports multi-page PDFs (up to 10 pages at 300 DPI).
    """
    if doc_type not in _EXTRACT_PROMPTS:
        return {"error": f"Unknown document type '{doc_type}'."}

    images = _bytes_to_base64_images(file_bytes, filename)

    # ── Step 1: transcribe all pages (bilingual OCR) ─────────────────────────
    content_blocks = [
        {
            "type": "text",
            "text": "Transcribe all text visible in this document. Include ALL Arabic and English text, every number, date, and code.",
        },
    ]
    for b64, media_type in images:
        content_blocks.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:{media_type};base64,{b64}",
                "detail": "high",
            },
        })

    ocr_resp = await client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": _OCR_SYSTEM},
            {"role": "user", "content": content_blocks},
        ],
        max_tokens=4000,
        temperature=0,
    )
    transcription = ocr_resp.choices[0].message.content.strip()
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
    extract_resp = await client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": _EXTRACT_PROMPTS[doc_type]},
            {"role": "user", "content": transcription},
        ],
        response_format={"type": "json_object"},
        max_tokens=2500,
        temperature=0,
    )

    raw = extract_resp.choices[0].message.content.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"error": f"Could not parse {doc_type.replace('_', ' ')} data."}
