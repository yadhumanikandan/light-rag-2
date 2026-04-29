PROMPT = (
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
)
