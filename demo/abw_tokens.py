"""Persona sign-in helper for the demo proofs (MSAL, public client `abw-test-client`).

Passwords come from .secrets\\personas.json (git-ignored). Nothing is ever printed except decoded,
non-secret token claims. ROPC is used ONLY for these synthetic demo users in this demo tenant.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jwt
import msal

ROOT = Path(__file__).resolve().parents[1]
ENTRA = json.loads((ROOT / "infra" / "generated" / "entra.json").read_text(encoding="utf-8"))
PERSONAS = json.loads((ROOT / ".secrets" / "personas.json").read_text(encoding="utf-8"))
TENANT = ENTRA["tenantId"]
CLIENT_ID = ENTRA["clients"]["test"]["appId"]

_app = msal.PublicClientApplication(CLIENT_ID, authority=f"https://login.microsoftonline.com/{TENANT}")


def scope_for(api_key: str, scope: str = "Tools.Read") -> str:
    return f"api://{ENTRA['apis'][api_key]['appId']}/{scope}"


def get_token(persona: str, api_key: str, scope: str = "Tools.Read") -> dict:
    """Return the MSAL result dict (access_token, expires_in, ...) or raise with the AAD error."""
    p = PERSONAS[persona]
    r = _app.acquire_token_by_username_password(p["upn"], p["password"], scopes=[scope_for(api_key, scope)])
    if "access_token" not in r:
        raise RuntimeError(f"{persona}/{api_key}: {r.get('error')}: {r.get('error_description', '')[:300]}")
    return r


def claims(token: str) -> dict:
    return jwt.decode(token, options={"verify_signature": False})


if __name__ == "__main__":
    who = sys.argv[1:] or ["priya", "wes"]
    for persona in who:
        for api in ("wall", "research", "actions"):
            try:
                c = claims(get_token(persona, api)["access_token"])
                print(f"{persona:6} -> {api:8} aud={c.get('aud')} ver={c.get('ver')} scp={c.get('scp')} roles={c.get('roles')} oid={c.get('oid')[:8]} azp={c.get('azp')}")
            except Exception as ex:  # noqa: BLE001
                print(f"{persona:6} -> {api:8} FAILED {ex}")
