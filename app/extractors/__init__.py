"""Two-step OCR (gpt-5) → Claude extraction for KYC documents.

Public API:
    extract_for_kyc(files, doc_type) → dict   — full field extraction
    classify_document(file_bytes, filename) → dict — single-doc classifier
"""

from app.extractors.extract import extract_for_kyc
from app.extractors.classify import classify_document

__all__ = ["extract_for_kyc", "classify_document"]
