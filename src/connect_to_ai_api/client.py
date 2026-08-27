## Client with Stub Mode

import os
import json
from openai import OpenAI
from dotenv import load_dotenv
from .schema import TriageOutput

load_dotenv()

STUB_RESPONSE = TriageOutput(
    category="other",
    urgency="low",
    confidence=0.0,
    reason="Stub mode: no model call made.",
)


def get_llm_client() -> OpenAI:
    return OpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
    )


def load_prompt(version: str = "v1") -> str:
    """Load the system prompt from a versioned file."""
    module_dir = os.path.dirname(__file__)
    path = os.path.join(module_dir, "prompts", f"triage-{version}.md")
    with open(path, "r") as f:
        return f.read()


def triage_message(text: str) -> TriageOutput:
    """Call the model to triage a support message."""
    if os.environ.get("LLM_STUB") == "1":
        return STUB_RESPONSE

    client = get_llm_client()
    system_prompt = load_prompt("v1")
    
    res = client.chat.completions.create(
        model=os.environ["LLM_MODEL"],
        messages=[
            {"role": "system", "content": "system_prompt"},
            {"role": "user", "content": json.dumps({"text":text})},
        ],
        temperature=0,
    )
    
    raw = res.choices[0].message.content
    print(f"RAW MODEL OUTPUT: \n{raw}\n")
    
    try:
        data = json.loads(raw)
        return TriageOutput(**data)
    except Exception:
        return STUB_RESPONSE