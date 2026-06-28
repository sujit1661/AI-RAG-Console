import fitz
import pandas as pd
from docx import Document
import os
import base64
import logging

logger = logging.getLogger(__name__)

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
        page_info.append((start_pos, end_pos, page_num + 1))
        current_pos = end_pos
    
    return text, page_info

def extract_image_text(path: str) -> str:
    """
    Extract text from an image using Groq's vision model.
    Falls back to a placeholder if the API is unavailable.
    Supports PNG, JPG, JPEG.
    """
    try:
        from groq import Groq
        from dotenv import load_dotenv
        load_dotenv()

        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            logger.warning("GROQ_API_KEY not set — cannot extract text from image")
            return ""

        # Read and base64-encode the image
        with open(path, "rb") as f:
            image_bytes = f.read()
        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        # Determine MIME type from extension
        ext = path.rsplit(".", 1)[-1].lower()
        mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext, "image/jpeg")

        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model="meta-llama/llama-4-scout-17b-16e-instruct",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{b64_image}"
                            }
                        },
                        {
                            "type": "text",
                            "text": (
                                "Analyze this image thoroughly and extract ALL information in structured text form:\n\n"
                                "1. TEXT: Extract every word, number, label, and title visible.\n"
                                "2. CHARTS/GRAPHS: Describe the chart type (bar, line, pie, etc.), "
                                "   all axis labels, legend entries, data values, and key trends "
                                "   (e.g. 'Revenue peaks at Q3 2023 with $2.4M, drops 15% in Q4').\n"
                                "3. TABLES: Reproduce all rows and columns as plain text.\n"
                                "4. DIAGRAMS/INFOGRAPHICS: Describe all elements, relationships, "
                                "   arrows, and annotations.\n"
                                "5. KEY INSIGHTS: Summarize the 2-3 most important data points "
                                "   a reader should know from this image.\n\n"
                                "Preserve all numbers exactly. Return only the extracted content, no commentary."
                            )
                        }
                    ]
                }
            ],
            temperature=0.0,
            max_tokens=4096,
        )
        extracted = response.choices[0].message.content or ""
        logger.info(f"Groq vision extracted {len(extracted)} chars from {os.path.basename(path)}")
        return extracted.strip()

    except Exception as e:
        logger.warning(f"Groq vision extraction failed for {path}: {e}")
        return ""

def extract_excel_text(path):
    """
    Extract text from Excel files (.xlsx, .xls).
    - Handles multiple sheets
    - Preserves column headers and row context
    - Converts each row to a readable sentence-like format for better RAG chunking
    - Includes sheet summaries (row/col counts, numeric stats)
    """
    xl = pd.ExcelFile(path)
    all_text = []

    for sheet_name in xl.sheet_names:
        df = xl.parse(sheet_name)

        # Drop completely empty rows and columns
        df = df.dropna(how="all").dropna(axis=1, how="all")

        if df.empty:
            continue

        sheet_lines = [f"## Sheet: {sheet_name}"]
        sheet_lines.append(f"Rows: {len(df)}, Columns: {len(df.columns)}")
        sheet_lines.append(f"Columns: {', '.join(str(c) for c in df.columns)}\n")

        # Numeric summary for numeric columns
        numeric_cols = df.select_dtypes(include="number").columns.tolist()
        if numeric_cols:
            sheet_lines.append("### Numeric Summary")
            for col in numeric_cols:
                col_data = df[col].dropna()
                if not col_data.empty:
                    sheet_lines.append(
                        f"- {col}: min={col_data.min():.2f}, max={col_data.max():.2f}, "
                        f"mean={col_data.mean():.2f}, sum={col_data.sum():.2f}"
                    )
            sheet_lines.append("")

        # Convert each row to readable text: "Column1: value1 | Column2: value2 ..."
        sheet_lines.append("### Data Rows")
        for idx, row in df.iterrows():
            parts = []
            for col in df.columns:
                val = row[col]
                if pd.notna(val):
                    parts.append(f"{col}: {val}")
            if parts:
                sheet_lines.append(" | ".join(parts))

        all_text.append("\n".join(sheet_lines))

    return "\n\n".join(all_text) if all_text else ""

def extract_docx_text(path):
    doc = Document(path)
    return "\n".join([p.text for p in doc.paragraphs])


# Plain-text extensions handled by extract_text_file
TEXT_EXTENSIONS = {".txt", ".md", ".markdown", ".rst", ".csv", ".log"}


def extract_text_file(path: str) -> str:
    """
    Extract text from plain-text files (.txt, .md, .markdown, etc.).
    Tries UTF-8 first, falls back to latin-1.
    """
    for encoding in ("utf-8", "latin-1"):
        try:
            with open(path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    logger.warning(f"Could not decode {path} as text")
    return ""