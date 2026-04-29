from app.extractors._attestation import ATTESTATION_BLOCK

PROMPT = (
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
    + ATTESTATION_BLOCK +
    "CRITICAL DATE RULES:\n"
    "- Convert any DD/MM/YYYY date to YYYY-MM-DD.\n"
    "- If both Hijri and Gregorian dates are shown, use Gregorian.\n\n"
    "IMPORTANT: Only extract values actually present in the text. Do NOT invent or guess.\n"
    "Set a field to null ONLY if genuinely absent."
)
