import fitz
import pandas as pd
from PIL import Image
import pytesseract
from docx import Document

def extract_pdf_text(path):
    """
    Extract text from PDF with page number tracking.
    Returns: (text, page_info) where page_info is a list of (start_char, end_char, page_num) tuples
    """
    doc = fitz.open(path)
    text = ""
    page_info = []
    current_pos = 0
    
    for page_num in range(len(doc)):
        page = doc[page_num]
        page_text = page.get_text()
        start_pos = current_pos
        end_pos = current_pos + len(page_text)
        text += page_text
        page_info.append((start_pos, end_pos, page_num + 1))  # 1-indexed page numbers
        current_pos = end_pos
    
    return text, page_info

def extract_image_text(path):
    image = Image.open(path)
    return pytesseract.image_to_string(image)

def extract_excel_text(path):
    df = pd.read_excel(path)
    return df.to_string()

def extract_docx_text(path):
    doc = Document(path)
    return "\n".join([p.text for p in doc.paragraphs])