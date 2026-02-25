import os
from groq import Groq
from dotenv import load_dotenv
from typing import Generator

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def generate_answer(context, question):
    """
    Generate answer from context and question.
    Args:
        context: String containing the context (already joined)
        question: String containing the user's question
    Returns:
        Tuple of (answer_text, token_usage_dict)
    """
    prompt = f"""You are a helpful AI assistant.
Answer strictly from the provided context.
If the answer is not found in the context, say 'Not found in documents.'

Context:
{context}

Question:
{question}

Answer:"""

    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1000,
        max_completion_tokens=1000
    )

    answer = response.choices[0].message.content
    
    # Extract token usage
    usage = {
        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
        "total_tokens": response.usage.total_tokens if response.usage else 0
    }
    
    return answer, usage

def generate_answer_stream(context, question) -> Generator:
    """
    Generate answer from context and question with streaming.
    Args:
        context: String containing the context (already joined)
        question: String containing the user's question
    Yields:
        For content chunks: ("chunk", chunk_text)
        For completion: ("usage", token_usage_dict)
    """
    prompt = f"""You are a helpful AI assistant.
Answer strictly from the provided context.
If the answer is not found in the context, say 'Not found in documents.'

Context:
{context}

Question:
{question}

Answer:"""

    stream = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1000,
        max_completion_tokens=1000,
        stream=True
    )

    usage = None
    for chunk in stream:
        if chunk.choices[0].delta.content is not None:
            yield ("chunk", chunk.choices[0].delta.content)
        
        # Capture usage from the last chunk
        if chunk.usage:
            usage = {
                "prompt_tokens": chunk.usage.prompt_tokens if chunk.usage else 0,
                "completion_tokens": chunk.usage.completion_tokens if chunk.usage else 0,
                "total_tokens": chunk.usage.total_tokens if chunk.usage else 0
            }
    
    # Yield usage at the end if available
    if usage:
        yield ("usage", usage)
    else:
        # Fallback if usage not available
        yield ("usage", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0})