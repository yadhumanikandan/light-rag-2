"""PDF-to-image rendering helpers shared by extract and classify."""
import base64

_RASTER_MEDIA = {
    "jpg":  "image/jpeg",
    "jpeg": "image/jpeg",
    "png":  "image/png",
    "webp": "image/webp",
}


def _ext(filename: str) -> str:
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def to_base64_images(file_bytes: bytes, filename: str) -> list[tuple[str, str]]:
    """All pages → list of (b64, media_type). PDFs render up to 10 pages at 300 DPI."""
    if _ext(filename) == "pdf":
        try:
            import fitz
        except ImportError:
            raise RuntimeError("Install pymupdf: pip install pymupdf")
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        out = []
        for i in range(min(len(doc), 10)):
            pix = doc[i].get_pixmap(dpi=300)
            out.append((base64.b64encode(pix.tobytes("png")).decode(), "image/png"))
        doc.close()
        return out
    media = _RASTER_MEDIA.get(_ext(filename), "image/jpeg")
    return [(base64.b64encode(file_bytes).decode(), media)]


def first_page_image(file_bytes: bytes, filename: str) -> tuple[str, str] | None:
    """Page 1 only at 150 DPI — used by classifier for ~4× smaller payload."""
    if _ext(filename) == "pdf":
        try:
            import fitz
        except ImportError:
            raise RuntimeError("Install pymupdf: pip install pymupdf")
        doc = fitz.open(stream=file_bytes, filetype="pdf")
        if len(doc) == 0:
            doc.close()
            return None
        pix = doc[0].get_pixmap(dpi=150)
        doc.close()
        return base64.b64encode(pix.tobytes("png")).decode(), "image/png"
    media = _RASTER_MEDIA.get(_ext(filename), "image/jpeg")
    return base64.b64encode(file_bytes).decode(), media
