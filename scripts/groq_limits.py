"""Show Groq rate-limit status with one tiny request. Never prints the key.

    python3 scripts/groq_limits.py
"""
import json
from pathlib import Path
import urllib.error
import urllib.request

env = {}
for line in (Path(__file__).resolve().parents[1] / ".env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip().removeprefix("export ").strip()] = v.strip().strip('"').strip("'")
key = env.get("GROQ_API_KEY", "")
model = env.get("GROQ_MODEL") or "openai/gpt-oss-120b"
print("key loaded:", bool(key), "| model:", model)
body = json.dumps({"model": model, "messages": [{"role": "user", "content": "hi"}],
                   "max_completion_tokens": 8}).encode()
req = urllib.request.Request("https://api.groq.com/openai/v1/chat/completions", data=body, method="POST",
                             headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                                      "User-Agent": "guardrailgen/1.0"})
try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        status, headers, text = resp.status, resp.headers, resp.read().decode()
except urllib.error.HTTPError as exc:
    status, headers, text = exc.code, exc.headers, exc.read().decode(errors="replace")
print("HTTP", status)
for name, value in headers.items():
    if "ratelimit" in name.lower() or name.lower() == "retry-after":
        print(f"  {name}: {value}")
try:
    error = json.loads(text).get("error")
    print("error:", error.get("message", "")[:400] if error else "none, request succeeded")
except ValueError:
    print("body:", text[:300])
