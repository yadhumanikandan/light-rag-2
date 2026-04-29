PROMPT = (
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
)
