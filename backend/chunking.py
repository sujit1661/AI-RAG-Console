from langchain_text_splitters import RecursiveCharacterTextSplitter

splitter = RecursiveCharacterTextSplitter(
    chunk_size=1000,
    chunk_overlap=300
)

def chunk_text(text):
    """Split text into chunks. Returns list of chunk strings."""
    return splitter.split_text(text)

def chunk_text_with_pages(text, page_info):
    """
    Split text into chunks while preserving page number information.
    Args:
        text: Full text string
        page_info: List of (start_char, end_char, page_num) tuples
    Returns:
        List of (chunk_text, page_num) tuples
    """
    chunks = splitter.split_text(text)
    chunk_with_pages = []
    
    for chunk in chunks:
        # Find which page this chunk belongs to by finding the middle character
        chunk_start = text.find(chunk)
        if chunk_start == -1:
            # Fallback: assign to first page
            chunk_with_pages.append((chunk, page_info[0][2] if page_info else None))
            continue
        
        chunk_mid = chunk_start + len(chunk) // 2
        
        # Find the page that contains the middle of this chunk
        page_num = None
        for start_pos, end_pos, pg_num in page_info:
            if start_pos <= chunk_mid < end_pos:
                page_num = pg_num
                break
        
        # If not found, use the closest page
        if page_num is None:
            if page_info:
                # Find closest page
                min_dist = float('inf')
                for start_pos, end_pos, pg_num in page_info:
                    dist = min(abs(chunk_mid - start_pos), abs(chunk_mid - end_pos))
                    if dist < min_dist:
                        min_dist = dist
                        page_num = pg_num
            else:
                page_num = None
        
        chunk_with_pages.append((chunk, page_num))
    
    return chunk_with_pages


def chunk_excel_text(text: str, rows_per_chunk: int = 20) -> list:
    """
    Chunk Excel text output by grouping rows together.
    Each chunk keeps the sheet header + a batch of rows so context is preserved.
    Args:
        text: Output from extract_excel_text()
        rows_per_chunk: How many data rows per chunk (default 50)
    Returns:
        List of chunk strings
    """
    chunks = []
    # Split by sheet sections
    sheet_sections = text.split("\n\n## Sheet:")
    for i, section in enumerate(sheet_sections):
        if not section.strip():
            continue
        # Re-add the header marker for all but the first (which already has it)
        header = "## Sheet:" if i > 0 else ""
        full_section = (header + section).strip()

        lines = full_section.split("\n")

        # Separate header lines (sheet name, row/col counts, summary) from data rows
        header_lines = []
        data_lines = []
        in_data = False
        for line in lines:
            if line.startswith("### Data Rows"):
                in_data = True
                continue
            if in_data:
                data_lines.append(line)
            else:
                header_lines.append(line)

        header_block = "\n".join(header_lines)

        if not data_lines:
            # No data rows — just add the header/summary as one chunk
            if header_block.strip():
                chunks.append(header_block.strip())
            continue

        # Batch data rows into chunks, each prefixed with the sheet header
        for start in range(0, len(data_lines), rows_per_chunk):
            batch = data_lines[start:start + rows_per_chunk]
            chunk = header_block + "\n### Data Rows\n" + "\n".join(batch)
            chunks.append(chunk.strip())

    # Fallback: if no sheet structure found, use regular splitter
    if not chunks:
        return splitter.split_text(text)

    return chunks
