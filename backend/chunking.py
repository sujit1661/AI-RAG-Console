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