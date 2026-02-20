import os
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

def generate_answer(question, context):

    joined_context = "\n\n".join(context)

    prompt = f"""
    You are a helpful AI assistant.
    Answer strictly from the provided context.
    If answer not found, say 'Not found in documents.'

    Context:
    {joined_context}

    Question:
    {question}
    """

    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )

    return response.choices[0].message.content