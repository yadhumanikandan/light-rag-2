"""Per-doctype Claude extraction prompts (one module per doc type)."""

from app.extractors.prompts.passport import PROMPT as PASSPORT
from app.extractors.prompts.emirates_id import PROMPT as EMIRATES_ID
from app.extractors.prompts.trade_license import PROMPT as TRADE_LICENSE
from app.extractors.prompts.ejari import PROMPT as EJARI
from app.extractors.prompts.moa import PROMPT as MOA
from app.extractors.prompts.insurance import PROMPT as INSURANCE
from app.extractors.prompts.residence_visa import PROMPT as RESIDENCE_VISA
from app.extractors.prompts.vat_certificate import PROMPT as VAT_CERTIFICATE
from app.extractors.prompts.board_resolution import PROMPT as BOARD_RESOLUTION
from app.extractors.prompts.poa import PROMPT as POA
from app.extractors.prompts.partners_annex import PROMPT as PARTNERS_ANNEX
from app.extractors.prompts.certificate_of_incorporation import PROMPT as CERTIFICATE_OF_INCORPORATION
from app.extractors.prompts.register_of_shareholders import PROMPT as REGISTER_OF_SHAREHOLDERS
from app.extractors.prompts.register_of_directors import PROMPT as REGISTER_OF_DIRECTORS
from app.extractors.prompts.certificate_of_good_standing import PROMPT as CERTIFICATE_OF_GOOD_STANDING
from app.extractors.prompts.free_zone_license import PROMPT as FREE_ZONE_LICENSE
from app.extractors.prompts.dcci_membership import PROMPT as DCCI_MEMBERSHIP
from app.extractors.prompts.renewal_receipt import PROMPT as RENEWAL_RECEIPT
from app.extractors.prompts.audited_financials import PROMPT as AUDITED_FINANCIALS
from app.extractors.prompts.ubo_declaration import PROMPT as UBO_DECLARATION
from app.extractors.prompts.specimen_signatures import PROMPT as SPECIMEN_SIGNATURES

PROMPTS: dict[str, str] = {
    "passport":                     PASSPORT,
    "emirates_id":                  EMIRATES_ID,
    "trade_license":                TRADE_LICENSE,
    "ejari":                        EJARI,
    "moa":                          MOA,
    "insurance":                    INSURANCE,
    "residence_visa":               RESIDENCE_VISA,
    "vat_certificate":              VAT_CERTIFICATE,
    "board_resolution":             BOARD_RESOLUTION,
    "poa":                          POA,
    "partners_annex":               PARTNERS_ANNEX,
    "certificate_of_incorporation": CERTIFICATE_OF_INCORPORATION,
    "register_of_shareholders":     REGISTER_OF_SHAREHOLDERS,
    "register_of_directors":        REGISTER_OF_DIRECTORS,
    "certificate_of_good_standing": CERTIFICATE_OF_GOOD_STANDING,
    "free_zone_license":            FREE_ZONE_LICENSE,
    "dcci_membership":              DCCI_MEMBERSHIP,
    "renewal_receipt":              RENEWAL_RECEIPT,
    "audited_financials":           AUDITED_FINANCIALS,
    "ubo_declaration":              UBO_DECLARATION,
    "specimen_signatures":          SPECIMEN_SIGNATURES,
}
