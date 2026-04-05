
# Fixed document_parser.py
# Fix: corrected unterminated string literal that was breaking startup

import logging

logger = logging.getLogger(__name__)

def parse_opportunity_file(file_path: str) -> dict:
    '''
    Safe document parsing wrapper.
    Attempts to extract text from files but fails gracefully so the API never crashes.
    '''

    extracted_text = ""

    try:
        # Try PyMuPDF first
        import fitz
        doc = fitz.open(file_path)
        pages = []
        for page in doc:
            pages.append(page.get_text())
        extracted_text = "\n".join(pages)
        doc.close()
        return {
            "parser": "pymupdf",
            "text": extracted_text
        }

    except Exception as pymupdf_error:
        logger.warning(f"PyMuPDF parsing failed: {pymupdf_error}")

    try:
        # Fallback to pypdf
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        pages = []
        for page in reader.pages:
            pages.append(page.extract_text() or "")
        extracted_text = "\n".join(pages)
        return {
            "parser": "pypdf",
            "text": extracted_text
        }

    except Exception as pypdf_error:
        logger.warning(f"PyPDF parsing failed: {pypdf_error}")

    return {
        "parser": "none",
        "text": "",
        "error": "No parser succeeded"
    }
