"""Localise the experiment's source texts with a live model (costs money, needs credentials).

    TG_MAX_LIVE_CALLS=160 uv run --group live python evals/l10n/generate.py

Each of the 40 English texts in sources.jsonl is localised into Dutch and Arabic under two
conditions: `rules` (the prompt contains the market's section of brand.yaml) and `bare` (it does
not). 40 x 2 x 2 = 160 requests.

Vertex AI through Application Default Credentials (GOOGLE_CLOUD_PROJECT and the usual ADC
variables in the environment); this script never reads, prints or stores credentials.
Every request counts toward TG_MAX_LIVE_CALLS (default 0: no calls at all). SDK retries are off,
so one request is one call. A failed call leaves a gap; running again requests only the ids
missing from documents.jsonl. `TG_ONLY=s01-nl-bare` limits a run to the listed ids (a smoke
test). Text is stored as returned, with the raw response, and never edited: labels live in
labels.jsonl.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

HERE = Path(__file__).resolve().parent
OUT = HERE / "documents.jsonl"
MODEL = os.environ.get("TG_GEMINI_MODEL", "gemini-3.6-flash")
LOCATION = os.environ.get("TG_GEMINI_LOCATION", "eu")
THINKING = "LOW"
MARKETS = {
    "nl": ("nl-NL", "Dutch-speaking business customers in the Netherlands"),
    "ar": ("ar", "Arabic-speaking business customers (Modern Standard Arabic)"),
}

SYSTEM = (
    "You localise marketing copy for ExampleFreight, a fictional logistics company. Everything "
    "is fictional. Localise the whole text and nothing else: add no claims, numbers or "
    "sentences of your own, and leave nothing out."
)


class Output(BaseModel):
    translation: str


def requests() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for line in (HERE / "sources.jsonl").read_text(encoding="utf-8").splitlines():
        src = json.loads(line)
        for lang in MARKETS:
            for condition in ("bare", "rules"):
                out.append(
                    {
                        "id": f"{src['id']}-{lang}-{condition}",
                        "source_id": src["id"],
                        "split": src["split"],
                        "market": MARKETS[lang][0],
                        "condition": condition,
                        "source": src["text"],
                    }
                )
    return out


def rules_block(brand: dict[str, Any], market: str) -> str:
    m = brand["markets"][market]
    lines = ["Brand rules for this market (follow every one):"]
    lines.append("- Keep these names exactly as written: " + ", ".join(brand["do_not_translate"]))
    for term in m.get("terms", []):
        lines.append(f'- For "{term["source"]}" use: ' + " / ".join(term["target"]))
    if m.get("forbidden"):
        lines.append("- Never use these phrases: " + "; ".join(m["forbidden"]))
    for required in m.get("required_lines", []):
        lines.append(f"- End with this line as its own paragraph, word for word: {required}")
    if m.get("address") == "informal":
        lines.append('- Address the reader informally ("je"), never with "u" or "uw".')
    elif m.get("address") == "formal":
        lines.append('- Address the reader formally ("u"), never with "je" or "jij".')
    lines.append("- Keep every number, written the way this language writes numbers.")
    return "\n".join(lines)


def prompt(req: dict[str, Any], brand: dict[str, Any]) -> str:
    audience = next(a for code, a in MARKETS.values() if code == req["market"])
    parts = [f"Localise the English text below for {audience}."]
    if req["condition"] == "rules":
        parts.append(rules_block(brand, req["market"]))
    parts.append("English text:\n" + req["source"])
    return "\n\n".join(parts)


class Budget:
    def __init__(self, cap: int):
        self.cap, self.used = cap, 0
        self._lock = threading.Lock()

    def take(self) -> bool:
        with self._lock:
            if self.used >= self.cap:
                return False
            self.used += 1
            return True


def main() -> int:
    cap = int(os.environ.get("TG_MAX_LIVE_CALLS", "0"))
    only = {x for x in os.environ.get("TG_ONLY", "").split(",") if x}
    brand = yaml.safe_load((HERE / "brand.yaml").read_text(encoding="utf-8"))
    todo = requests()
    done: dict[str, dict[str, Any]] = {}
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            row = json.loads(line)
            if "id" in row:
                done[row["id"]] = row
    todo = [r for r in todo if r["id"] not in done and (not only or r["id"] in only)]
    print(f"{len(done)} documents on file, {len(todo)} to request, cap {cap} calls")
    if not todo or cap <= 0:
        return 0 if not todo else 2

    from google import genai
    from google.genai import types

    client = genai.Client(
        vertexai=True,
        location=LOCATION,
        http_options=types.HttpOptions(
            timeout=120_000, retry_options=types.HttpRetryOptions(attempts=1)
        ),
    )
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM,
        response_mime_type="application/json",
        response_schema=Output,
        thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel(THINKING)),
    )
    budget = Budget(cap)
    lock = threading.Lock()
    failures: list[str] = []

    def run(req: dict[str, Any]) -> None:
        if not budget.take():
            with lock:
                failures.append(f"{req['id']}: cap reached, not requested")
            return
        try:
            resp = client.models.generate_content(
                model=MODEL, contents=prompt(req, brand), config=config
            )
            out = Output.model_validate_json(resp.text or "")
        except Exception as exc:  # vendor errors by type and status only
            code = getattr(exc, "code", None)
            with lock:
                failures.append(
                    f"{req['id']}: {type(exc).__name__}" + (f" (HTTP {code})" if code else "")
                )
            return
        row = {
            **{k: req[k] for k in ("id", "source_id", "split", "market", "condition")},
            "target": out.translation,
            "raw_response": resp.text,  # the model's exact output, kept as evidence
        }
        with lock:
            done[req["id"]] = row

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(run, todo))

    template = SYSTEM + json.dumps(MARKETS) + rules_block(brand, "nl-NL") + rules_block(brand, "ar")
    meta = {
        "model": MODEL,
        "location": LOCATION,
        "thinking_level": THINKING.lower(),
        "prompt_sha256": hashlib.sha256(template.encode()).hexdigest()[:16],
        "generated_at": dt.datetime.now(dt.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    rows = [done[k] for k in sorted(done)]
    OUT.write_text(
        json.dumps({"meta": meta})
        + "\n"
        + "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    print(f"calls used: {budget.used}; documents on file: {len(rows)}")
    for f in failures:
        print("FAILED " + f)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
