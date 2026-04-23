"""
NAS (SMB/CIFS) storage helper for archiving KYC documents to the office network share.

Target layout:
  \\\\<NAS_SERVER>\\BANKS\\<company_name>\\<filename.docx>

Design principles:
  - Non-fatal: callers continue normally even when NAS is unreachable.
  - Session-cached: smbprotocol reuses the TCP connection across requests.
  - Idempotent: makedirs(exist_ok=True) means re-runs never error on existing folders.
"""

import logging
import re
from typing import Optional

from app.config import NAS_SERVER, NAS_USER, NAS_PASSWORD, NAS_SHARE

logger = logging.getLogger(__name__)

# Windows/SMB path characters that are illegal in folder/file names
_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|]')


def _sanitise_name(name: str) -> str:
    """
    Return a Windows-safe folder name derived from the company name.

    - Strips SMB-illegal characters (replaces with underscore)
    - Collapses consecutive whitespace / underscores
    - Trims leading/trailing dots and spaces (Windows restriction)
    - Hard-caps at 100 characters so the full UNC path stays well under MAX_PATH
    """
    safe = _ILLEGAL_CHARS.sub("_", name).strip().strip(".")
    safe = re.sub(r"[\s_]+", "_", safe)
    return safe[:100] or "Unknown_Company"


def save_to_nas(
    docx_bytes: bytes,
    filename: str,
    company_name: str,
    original_files: Optional[dict[str, tuple[str, bytes]]] = None,
) -> Optional[str]:
    """
    Create a company folder under BANKS, save every original uploaded document,
    then save the generated KYC DOCX.

    Args:
        docx_bytes:     Raw bytes of the generated Word document.
        filename:       Target DOCX file name (e.g. "KYC_Acme_LLC.docx").
        company_name:   Company name from the Trade Licence — becomes the folder name.
        original_files: Mapping of doc_type → (original_filename, file_bytes) for every
                        document the user uploaded. Each file is saved as
                        "{doc_type}{original_extension}" so the folder contains e.g.:
                          trade_license.pdf
                          ejari.jpg
                          passport.pdf
                          KYC_Acme_LLC.docx

    Returns:
        The UNC folder path on success, None on any failure (non-fatal).
    """
    try:
        import smbclient
        from smbprotocol.exceptions import SMBException
    except ImportError:
        logger.warning(
            "smbprotocol is not installed — NAS archiving disabled. "
            "Run: pip install smbprotocol"
        )
        return None

    folder_name = _sanitise_name(company_name)
    unc_folder  = f"\\\\{NAS_SERVER}\\{NAS_SHARE}\\{folder_name}"
    print(f"[NAS] target folder: {unc_folder}", flush=True)

    try:
        print(f"[NAS] registering session to {NAS_SERVER} as {NAS_USER}…", flush=True)
        smbclient.register_session(
            server=NAS_SERVER,
            username=NAS_USER,
            password=NAS_PASSWORD,
            connection_timeout=10,
        )
        print("[NAS] session OK", flush=True)

        smbclient.makedirs(unc_folder, exist_ok=True)
        print(f"[NAS] folder ready: {unc_folder}", flush=True)

        # ── Save every original uploaded document ────────────────────────────
        if original_files:
            for doc_type, (orig_filename, file_bytes) in original_files.items():
                ext = ""
                if "." in orig_filename:
                    ext = "." + orig_filename.rsplit(".", 1)[-1].lower()
                nas_name = f"{doc_type}{ext}"
                with smbclient.open_file(f"{unc_folder}\\{nas_name}", mode="wb") as fh:
                    fh.write(file_bytes)
                print(f"[NAS] wrote {nas_name} ({len(file_bytes):,} bytes)", flush=True)

        # ── Save the generated KYC report ────────────────────────────────────
        with smbclient.open_file(f"{unc_folder}\\{filename}", mode="wb") as fh:
            fh.write(docx_bytes)
        print(f"[NAS] wrote {filename} ({len(docx_bytes):,} bytes)", flush=True)

        return unc_folder

    except SMBException as exc:
        print(f"[NAS] SMBException: {exc}", flush=True)
        logger.error("NAS SMB error: %s", exc)
        return None
    except OSError as exc:
        print(f"[NAS] OSError: {exc}", flush=True)
        logger.error("NAS OS error: %s", exc)
        return None
    except Exception as exc:
        print(f"[NAS] unexpected {type(exc).__name__}: {exc}", flush=True)
        logger.exception("NAS unexpected error: %s", exc)
        return None
