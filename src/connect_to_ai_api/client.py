import os
import json
import time
from datetime import datetime
from openai import OpenAI, APIError, APITimeoutError
from dotenv import load_dotenv
from .schema import TriageOutput
from fastapi import HTTPException

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
        timeout=30.0, 
    )


def load_prompt(version: str = "v1") -> str:
    module_dir = os.path.dirname(__file__)
    path = os.path.join(module_dir, "prompts", f"triage-{version}.md")
    with open(path, "r") as f:
        return f.read()


def parse_model_output(raw: str) -> dict:
    """Strip markdown fences and parse JSON."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    return json.loads(raw)


def quarantine_log(input_text: str, raw_output: str, error: str, prompt_version: str):
    """Write a failed attempt to quarantine for later inspection."""
    os.makedirs("logs", exist_ok=True)
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "prompt_version": prompt_version,
        "input": input_text,
        "raw_output": raw_output,
        "error": error,
    }
    with open("logs/quarantine.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")


def call_model(client: OpenAI, messages: list, model: str) -> str:
    """Make one model call with timeout."""
    res = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
    )
    return res.choices[0].message.content


def triage_message(text: str) -> TriageOutput:
    """Call the model to triage a support message."""
    if os.environ.get("LLM_STUB") == "1":
        return STUB_RESPONSE

    client = get_llm_client()
    model = os.environ["LLM_MODEL"]
    prompt_version = "v1"
    system_prompt = load_prompt(prompt_version)

    # First attempt
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps({"text": text})},
    ]

    try:
        raw = call_model(client, messages, model)
    except APITimeoutError:
        raise HTTPException(status_code=504, detail="Model call timed out")
    except APIError as e:
        raise HTTPException(status_code=502, detail=f"Model API error: {e}")

    # Try to parse and validate
    parsed, error = _try_parse_validate(raw)
    
    if parsed is not None:
        return parsed

    repair_messages = messages + [
        {"role": "assistant", "content": raw},
        {
            "role": "user",
            "content": (
                f"Your previous answer was rejected. Error: {error}\n"
                "Return only corrected JSON matching the schema. No extra text."
            ),
        },
    ]

    try:
        raw_repair = call_model(client, repair_messages, model)
    except Exception as e:
        quarantine_log(text, raw, str(e), prompt_version)
        raise HTTPException(status_code=422, detail="Model repair failed")

    parsed_repair, error_repair = _try_parse_validate(raw_repair)

    if parsed_repair is not None:
        return parsed_repair

    quarantine_log(text, raw_repair, error_repair, prompt_version)
    raise HTTPException(status_code=422, detail="Model output could not be repaired")


def _try_parse_validate(raw: str) -> tuple[TriageOutput | None, str]:
    """Try to parse raw text into TriageOutput. Returns (output, error_message)."""
    try:
        data = parse_model_output(raw)
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {e}"
    except Exception as e:
        return None, f"Parse error: {e}"

    try:
        output = TriageOutput.model_validate(data)
    except Exception as e:
        return None, f"Schema validation failed: {e}"

    return output, ""
