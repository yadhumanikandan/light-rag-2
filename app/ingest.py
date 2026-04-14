import os
from pathlib import Path
from app.rag import get_rag


def extract_text_from_pdf(filepath: str) -> str:
    import PyPDF2
    text = ""
    with open(filepath, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            text += page.extract_text() + "\n"
    return text


def extract_text_from_docx(filepath: str) -> str:
    from docx import Document
    doc = Document(filepath)
    return "\n".join([para.text for para in doc.paragraphs if para.text.strip()])


def extract_text_from_txt(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def extract_text_from_pptx(filepath: str) -> str:
    from pptx import Presentation
    prs = Presentation(filepath)
    lines = []
    for slide in prs.slides:
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = para.text.strip()
                    if text:
                        lines.append(text)
    return "\n".join(lines)


def extract_text_from_xlsx(filepath: str) -> str:
    import openpyxl
    wb = openpyxl.load_workbook(filepath, data_only=True)
    lines = []
    for sheet in wb.worksheets:
        lines.append(f"[Sheet: {sheet.title}]")
        for row in sheet.iter_rows(values_only=True):
            row_text = "\t".join(str(cell) for cell in row if cell is not None)
            if row_text.strip():
                lines.append(row_text)
    return "\n".join(lines)


def extract_text_from_csv(filepath: str) -> str:
    import csv
    lines = []
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f)
        for row in reader:
            row_text = "\t".join(row)
            if row_text.strip():
                lines.append(row_text)
    return "\n".join(lines)


def extract_text(filepath: str) -> str:
    ext = Path(filepath).suffix.lower()
    if ext == ".pdf":
        return extract_text_from_pdf(filepath)
    elif ext == ".docx":
        return extract_text_from_docx(filepath)
    elif ext in [".txt", ".md"]:
        return extract_text_from_txt(filepath)
    elif ext == ".pptx":
        return extract_text_from_pptx(filepath)
    elif ext in [".xlsx", ".xls"]:
        return extract_text_from_xlsx(filepath)
    elif ext == ".csv":
        return extract_text_from_csv(filepath)
    else:
        raise ValueError(f"Unsupported file type: {ext}")


async def ingest_file(filepath: str) -> dict:
    """Extract text from file and insert into LightRAG."""
    rag = get_rag()
    filename = Path(filepath).name

    try:
        text = extract_text(filepath)
        if not text.strip():
            return {"success": False, "filename": filename, "error": "File appears to be empty or unreadable"}

        await rag.ainsert(text, file_paths=[filepath])

        return {"success": True, "filename": filename, "chars": len(text)}
    except Exception as e:
        return {"success": False, "filename": filename, "error": str(e)}


async def ingest_directory(directory: str) -> list:
    """Ingest all supported files in a directory."""
    dir_path = Path(directory)
    if not dir_path.exists():
        return []
    results = []
    supported = [".pdf", ".docx", ".txt", ".md", ".pptx", ".xlsx", ".xls", ".csv"]
    for f in dir_path.iterdir():
        if f.suffix.lower() in supported:
            result = await ingest_file(str(f))
            results.append(result)
    return results
