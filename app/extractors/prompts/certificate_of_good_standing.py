from app.extractors._attestation import ATTESTATION_BLOCK

PROMPT = (
    "You are an expert document data extractor. The text below was transcribed from a "
    "Certificate of Good Standing / Incumbency certificate issued by a corporate registry.\n\n"
    "Extract ALL of the following fields and return ONLY a valid JSON object:\n\n"
    "COMPANY:\n"
    '- "company_name": Company name as printed.\n'
    '- "status": Company status as stated (e.g., "Good Standing", "Active", "In Good Standing").\n'
    '- "date_of_issue": Date the certificate was issued in YYYY-MM-DD.\n'
    '- "issuing_authority": Issuing registrar / authority name.\n'
    '- "registration_number": Company registration number, null if absent.\n\n'
    + ATTESTATION_BLOCK +
    "IMPORTANT: Only extract values actually present in the text. Do NOT invent or guess.\n"
    "Set a field to null ONLY if genuinely absent."
)
