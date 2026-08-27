## Clien with Stub Mode

import os 
from openai import OpenAI
from dotenv import load_dotenv
from .schema import TriageOutput

load_dotenv()

STUB_RESPONSE = TriageOutput(
    category = "other",
    urgency = "low",
    confidence = 0.0,
    reason="Stub mode: no model call made.",
)

def get_llm_client() -> OpenAI:
    return OpenAI(
        base_url = os.environ["LLM_BASE_URL"],
        api_key = os.environ["LLM_API_KEY"],
    )
    
def triage_message(text: str) -> TriageOutput:
    """Call the model to triage a support message."""
    if os.environ.get("LLM_STUB") == "1":
        return STUB_RESPONSE
    
    client = get_llm_client()