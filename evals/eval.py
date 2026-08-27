import json
import requests
import sys
from datetime import datetime

BASE_URL = "http://localhost:8000"
CASES_FILE = "evals/cases.json"


def run_eval():
    with open(CASES_FILE, "r") as f:
        cases = json.load(f)

    passed = 0
    failed = []
    total = len(cases)

    print(f"Running {total} eval cases against {BASE_URL}/triage")
    print(f"Date: {datetime.utcnow().isoformat()}")
    print("=" * 60)

    for i, case in enumerate(cases, 1):
        text = case["input"]
        expected = case["expected"]

        try:
            res = requests.post(
                f"{BASE_URL}/triage",
                json={"text": text},
                timeout=10,
            )
        except Exception as e:
            print(f"[{i}/{total}] FAIL (request error): {e}")
            failed.append({"case": i, "input": text, "error": str(e)})
            continue

        if res.status_code != 200:
            print(f"[{i}/{total}] FAIL (HTTP {res.status_code}): {text[:50]}...")
            failed.append({"case": i, "input": text, "status": res.status_code, "body": res.text})
            continue

        actual = res.json()

        # Check category match (primary metric)
        if actual.get("category") == expected["category"]:
            passed += 1
            status = "PASS"
        else:
            status = "FAIL"
            failed.append({
                "case": i,
                "input": text,
                "expected_category": expected["category"],
                "actual": actual,
            })

        print(f"[{i}/{total}] {status}: {text[:50]}... → category={actual.get('category')}")

    print("=" * 60)
    print(f"Score: {passed}/{total} ({passed/total*100:.0f}%)")
    print(f"Prompt version: v1")
    print(f"Date: {datetime.utcnow().isoformat()}")

    if failed:
        print(f"\nFailed cases ({len(failed)}):")
        for f in failed:
            print(f"  Case {f['case']}: {f['input'][:50]}...")

    # Write result
    result = {
        "date": datetime.utcnow().isoformat(),
        "prompt_version": "v1",
        "score": f"{passed}/{total}",
        "percentage": f"{passed/total*100:.0f}%",
        "failed_cases": len(failed),
    }
    with open("evals/result.json", "w") as f:
        json.dump(result, f, indent=2)

    return passed, total


if __name__ == "__main__":
    run_eval()