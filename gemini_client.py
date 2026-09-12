"""
Shared Gemini client factory.

As of late 2026, Google has been restricting new Gemini API key creation
to service-account-bound keys (the "AQ." prefix) for a growing number of
accounts/projects — these do NOT work with the classic
`genai.Client(api_key="AQ...")` flow (401 ACCESS_TOKEN_TYPE_UNSUPPORTED).
The supported way to use a service-account-bound credential is Vertex AI
mode, authenticating with the service account's own JSON key directly —
that's what this module sets up.

Configure via environment variables (.env locally, Vercel Environment
Variables in production):

  GOOGLE_CLOUD_PROJECT                 - GCP project id (e.g. "my-project-123")
  GOOGLE_CLOUD_LOCATION                - region, default "global" (Gemini 3.x
                                          models are mostly only served from
                                          the "global" endpoint as of late
                                          2026 — a regional value like
                                          "us-central1" throws 404 NOT_FOUND
                                          on the publisher model)
  GOOGLE_APPLICATION_CREDENTIALS_JSON   - the FULL contents of the
                                          downloaded service-account .json
                                          key file, as one string

If those aren't set (or something inside them fails), this falls back to
the classic API-key path via GEMINI_API_KEY — so if Google ever restores
plain AIzaSy-style keys for this account, nothing else needs to change,
just set GEMINI_API_KEY and unset/leave blank the Vertex AI vars.

Every agent should import get_genai_client() from here instead of
constructing its own genai.Client(...).
"""
import os
import json

_client = None
_client_initialized = False
_last_error = ""


def get_genai_client():
    """Returns a configured google-genai Client, or None if nothing is configured/working."""
    global _client, _client_initialized, _last_error
    if _client_initialized:
        return _client
    _client_initialized = True

    try:
        from google import genai
    except ImportError as e:
        _last_error = f"google-genai package not installed: {e}"
        print(f"Gemini client error: {_last_error}")
        return None

    project = os.getenv("GOOGLE_CLOUD_PROJECT", "").strip()
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "global").strip()
    creds_json = os.getenv("GOOGLE_APPLICATION_CREDENTIALS_JSON", "").strip()

    # ── Preferred path: Vertex AI with an explicit service-account credential ──
    if project and creds_json:
        try:
            from google.oauth2 import service_account
            info = json.loads(creds_json)
            credentials = service_account.Credentials.from_service_account_info(
                info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )
            _client = genai.Client(
                vertexai=True, project=project, location=location, credentials=credentials
            )
            return _client
        except Exception as e:
            _last_error = f"Vertex AI client init error: {e}"
            print(f"Gemini client error: {_last_error}")
            # fall through to API-key path below rather than give up entirely

    # ── Fallback: classic API-key based client ──
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if api_key:
        try:
            _client = genai.Client(api_key=api_key)
            return _client
        except Exception as e:
            _last_error = f"Gemini API-key client init error: {e}"
            print(f"Gemini client error: {_last_error}")

    _last_error = "No working Gemini credentials configured (checked Vertex AI service account and GEMINI_API_KEY)."
    return None


def get_last_error() -> str:
    return _last_error
