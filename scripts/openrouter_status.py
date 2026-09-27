"""Show which OpenRouter key .env provides and its credit status. Never prints the key.

    python3 scripts/openrouter_status.py
"""
import json
from pathlib import Path
import urllib.error
import urllib.request

lines = [l for l in (Path(__file__).resolve().parents[1] / ".env").read_text(encoding="utf-8").splitlines()
         if l.strip().removeprefix("export ").startswith("OPENROUTER_API_KEY")]
print("OPENROUTER_API_KEY lines in .env:", len(lines), "(the LAST one is used)")
key = lines[-1].split("=", 1)[1].strip().strip('"').strip("'") if lines else ""
print("key present:", bool(key), "| ends with:", key[-4:] if len(key) > 8 else "?")
for url in ("https://openrouter.ai/api/v1/key", "https://openrouter.ai/api/v1/credits"):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + key, "User-Agent": "guardrailgen/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode()).get("data", {})
    except urllib.error.HTTPError as exc:
        data = {"http_error": exc.code, "body": exc.read().decode(errors="replace")[:200]}
    safe = {k: v for k, v in data.items() if k not in ("label",)}
    print(url.rsplit("/", 1)[1] + ":", json.dumps(safe))
