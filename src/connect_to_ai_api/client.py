import os
import json
import time
from datetime import datetime
from openai import OpenAI, APIError, APITimeoutError, RateLimitError
from dotenv import load_dotenv
from fastapi import HTTPException
from .schema import TriageOutput

load_dotenv()

STUB_RESPONSE = TriageOutput(
    category="other",
    urgency="low",
    confidence=0.0,
    reason="Stub mode: no model call made.",
)

FALLBACK_RESPONSE = TriageOutput(
    category="other",
    urgency="low",
    confidence=0.0,
    reason="LLM disabled: deterministic fallback.",
)


def get_llm_client() -> OpenAI:
    return OpenAI(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        timeout=30.0,  # explicit timeout, not SDK's 10-minute default
        max_retries=0,  # we handle retries ourselves
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


def cost_log(
    prompt_version: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    duration_ms: int,
    repair_count: int,
):
    """Structured cost log line."""
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "prompt_version": prompt_version,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "duration_ms": duration_ms,
        "repair_count": repair_count,
    }
    print(json.dumps(entry))  # stdout for log aggregation


def call_model_with_retry(client: OpenAI, messages: list, model: str, text: str) -> tuple[str, int]:
    """
    Call model with retry policy:
    - Retry on: timeout, 429, 5xx
    - Never retry on: 400, 401, 403
    - Exponential backoff with jitter: 1s, 2s, 4s
    """
    import random
    max_retries = 3
    base_delays = [1, 2, 4]  # seconds

    for attempt in range(max_retries):
        start = time.time()
        try:
            res = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
            )
            duration_ms = int((time.time() - start) * 1000)
            return res.choices[0].message.content, duration_ms

        except APITimeoutError:
            if attempt == max_retries - 1:
                raise HTTPException(status_code=504, detail="Model call timed out after retries")
            delay = base_delays[attempt] + random.uniform(0, 0.5)
            time.sleep(delay)

        except RateLimitError as e:
            if attempt == max_retries - 1:
                raise HTTPException(status_code=429, detail="Rate limited after retries")
            # Check for Retry-After header
            retry_after = None
            if hasattr(e, 'response') and e.response:
                retry_after = e.response.headers.get('retry-after')
            if retry_after:
                time.sleep(float(retry_after))
            else:
                delay = base_delays[attempt] + random.uniform(0, 0.5)
                time.sleep(delay)

        except APIError as e:
            status = getattr(e, 'status_code', None) or getattr(e, 'code', None)
            # Never retry on 4xx client errors (except 429 handled above)
            if status in (400, 401, 403):
                raise HTTPException(status_code=status, detail=f"Client error: {e}")
            # Retry on 5xx
            if attempt == max_retries - 1:
                raise HTTPException(status_code=502, detail=f"Model API error: {e}")
            delay = base_delays[attempt] + random.uniform(0, 0.5)
            time.sleep(delay)

    raise HTTPException(status_code=502, detail="All retries exhausted")


def triage_message(text: str) -> TriageOutput:
    """Call the model to triage a support message."""
    if os.environ.get("LLM_ENABLED", "true").lower() == "false":
        return FALLBACK_RESPONSE

    if os.environ.get("LLM_STUB") == "1":
        return STUB_RESPONSE

    client = get_llm_client()
    model = os.environ["LLM_MODEL"]
    prompt_version = "v1"
    system_prompt = load_prompt(prompt_version)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps({"text": text})},
    ]

    # First attempt
    start_total = time.time()
    raw, duration_ms = call_model_with_retry(client, messages, model, text)
    repair_count = 0

    parsed, error = _try_parse_validate(raw)

    if parsed is not None:
        # Log cost for happy path
        cost_log(prompt_version, model, 0, 0, duration_ms, repair_count)
        return parsed

    repair_count = 1
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

    raw_repair, duration_ms_repair = call_model_with_retry(client, repair_messages, model, text)
    total_duration_ms = int((time.time() - start_total) * 1000)

    parsed_repair, error_repair = _try_parse_validate(raw_repair)

    if parsed_repair is not None:
        cost_log(prompt_version, model, 0, 0, total_duration_ms, repair_count)
        return parsed_repair

    # --- QUARANTINE ---
    quarantine_log(text, raw_repair, error_repair, prompt_version)
    cost_log(prompt_version, model, 0, 0, total_duration_ms, repair_count)
    raise HTTPException(status_code=422, detail="Model output could not be repaired")


def _try_parse_validate(raw: str) -> tuple[TriageOutput | None, str]:
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