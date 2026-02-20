import fitz
import pandas as pd
from PIL import Image
import pytesseract
from docx import Document

def extract_pdf_text(path):
    doc = fitz.open(path)
    text = ""
    for page in doc:
        text += page.get_text()
    return text

def extract_image_text(path):
    image = Image.open(path)
    return pytesseract.image_to_string(image)

def extract_excel_text(path):
    df = pd.read_excel(path)
    return df.to_string()

def extract_docx_text(path):
    doc = Document(path)
    return "\n".join([p.text for p in doc.paragraphs])