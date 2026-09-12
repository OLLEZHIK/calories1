"""
Quick standalone check that Vertex AI credentials in .env actually work.

Usage (from the project root, after copying vertex_env_snippet.txt into .env):
    python test_vertex.py
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="backslashreplace")

import config  # noqa: F401  -- this loads .env into os.environ as a side effect
from gemini_client import get_genai_client, get_last_error

client = get_genai_client()
if client is None:
    print("FAILED to build a Gemini client at all.")
    print("Last error:", get_last_error())
    raise SystemExit(1)

try:
    resp = client.models.generate_content(
        model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
        contents="Ответь одним словом: ок",
    )
    print("SUCCESS! Model replied:", resp.text)
    print("\nEsli vidish' eto soobshenie - Vertex AI podklyuchen i rabotaet.")
except Exception as e:
    safe_error = str(e).encode("ascii", "backslashreplace").decode()
    print("ERROR calling the model:", type(e).__name__, safe_error)
    print(
        "\nEsli oshibka pro 'permission denied' ili 403 - podozhdite paru minut "
        "(IAM-rolyam nuzhno vremya na primenenie) i poprobuyte snova."
    )
