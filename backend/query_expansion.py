"""
Query expansion: rewrites the user query into multiple variations
so retrieval catches synonyms and related terms.
Uses the same Groq LLM — fast and free.
"""
import os
import logging
from typing import List

logger = logging.getLogger(__name__)


def expand_query(question: str) -> List[str]:
    """
    Generate 3 query variations for the original question.
    Returns [original] + [variations] — always includes the original.
    Falls back to [original] if LLM call fails.
    """
    try:
        from groq import Groq
        from dotenv import load_dotenv
        load_dotenv()

        client = Groq(api_key=os.getenv("GROQ_API_KEY"))

        prompt = f"""Generate 3 different search queries to find information related to this question.
Each query should use different words/synonyms but mean the same thing.
Return ONLY the 3 queries, one per line, no numbering, no explanation.

Question: {question}

Queries:"""

        response = client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=150,
        )

        raw = response.choices[0].message.content.strip()
        variations = [q.strip() for q in raw.split("\n") if q.strip()][:3]

        all_queries = [question] + variations
        logger.info(f"Query expanded: {len(all_queries)} variants for: {question[:60]}")
        return all_queries

    except Exception as e:
        logger.warning(f"Query expansion failed (using original): {e}")
        return [question]
