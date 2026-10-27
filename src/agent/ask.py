"""Ask a Foundry agent a question as a persona (or the signed-in Azure CLI user) and show the governed trail.

Examples
    python src\\agent\\ask.py --agent abw-wall-desk "List my wall crossings"
    python src\\agent\\ask.py --agent abw-wall-desk --persona priya "Summarise Project Falcon"
    python src\\agent\\ask.py --agent abw-wall-desk --approve yes "Buy 100 ACME"

Consent: the first call by a user per connection returns an OAuth consent link (Foundry OAuth identity
passthrough). Open it once in a browser as that user, then press Enter - or re-run the command.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import pathlib
import sys
import time
import webbrowser
from typing import Any

import msal
from azure.core.credentials import AccessToken, TokenCredential
from azure.identity import AzureCliCredential, CredentialUnavailableError
from azure.ai.projects import AIProjectClient
from openai import APIConnectionError, APIStatusError

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import netfix  # noqa: E402
from abw_agents import ROOT, load_state, project_endpoint  # noqa: E402

netfix.install()

logger = logging.getLogger(__name__)

AZURE_CLI_CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
SECRETS = ROOT / ".secrets"
EVIDENCE = ROOT / "demo" / "evidence"


class PersonaCredential(TokenCredential):
    """Device-code sign-in as a persona (Azure CLI public client); the refresh token is cached per persona."""

    def __init__(self, persona: str, tenant_id: str, upn: str) -> None:
        self._upn = upn
        self._path = SECRETS / f"msal-{persona}.json"
        self._cache = msal.SerializableTokenCache()
        if self._path.exists():
            self._cache.deserialize(self._path.read_text(encoding="utf-8"))
        self._app = msal.PublicClientApplication(
            AZURE_CLI_CLIENT_ID, authority=f"https://login.microsoftonline.com/{tenant_id}", token_cache=self._cache
        )

    def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        result = None
        accounts = self._app.get_accounts(username=self._upn)
        if accounts:
            result = self._app.acquire_token_silent(list(scopes), account=accounts[0])
        if not result:
            flow = self._app.initiate_device_flow(scopes=list(scopes))
            if "user_code" not in flow:
                raise RuntimeError(f"device flow failed: {flow}")
            print(f"\n>> Sign in as {self._upn}: {flow['message']}\n", flush=True)
            result = self._app.acquire_token_by_device_flow(flow)
        if "access_token" not in result:
            raise RuntimeError(f"sign-in failed: {result.get('error')}: {result.get('error_description')}")
        if self._cache.has_state_changed:
            self._path.write_text(self._cache.serialize(), encoding="utf-8")
        return AccessToken(result["access_token"], int(time.time()) + int(result.get("expires_in", 3000)))


class AzCliCacheCredential(TokenCredential):
    """Operator token read from the Azure CLI's own encrypted MSAL cache (the tokens `az login` already minted).

    Starting `az` costs 8-15 s on some Windows laptops and times out while another `az` command runs, so ask the
    cache directly (same approach as demo\\mcpclient.py) and fall back to the CLI only when the cache cannot answer.
    """

    def __init__(self, tenant_id: str, upn: str | None) -> None:
        self._tenant_id = tenant_id
        self._upn = upn
        self._app: msal.PublicClientApplication | None = None
        self._cli = AzureCliCredential(process_timeout=90)

    def _from_cache(self, scopes: tuple[str, ...]) -> AccessToken | None:
        try:
            if self._app is None:
                from msal_extensions import PersistedTokenCache, build_encrypted_persistence

                cache = PersistedTokenCache(build_encrypted_persistence(str(pathlib.Path.home() / ".azure" / "msal_token_cache.bin")))
                self._app = msal.PublicClientApplication(
                    AZURE_CLI_CLIENT_ID, authority=f"https://login.microsoftonline.com/{self._tenant_id}", token_cache=cache
                )
            accounts = self._app.get_accounts(username=self._upn) if self._upn else []
            result = self._app.acquire_token_silent(list(scopes), account=accounts[0]) if accounts else None
        except Exception as exc:  # unreadable/locked cache or unsupported platform: let the CLI answer
            logger.debug("az token cache not usable: %s", exc)
            return None
        if result and "access_token" in result:
            return AccessToken(result["access_token"], int(time.time()) + int(result.get("expires_in", 3000)))
        return None

    def get_token(self, *scopes: str, **kwargs: Any) -> AccessToken:
        return self._from_cache(scopes) or self._cli.get_token(*scopes, **kwargs)


def build_credential(persona: str | None) -> tuple[TokenCredential, str]:
    cfg = load_state("config")
    if not persona:
        return AzCliCacheCredential(cfg["tenantId"], cfg.get("operatorUpn")), "az-cli (signed-in operator)"
    personas = json.loads((SECRETS / "personas.json").read_text(encoding="utf-8-sig"))
    entry = personas[persona] if isinstance(personas, dict) and persona in personas else next(
        p for p in personas if str(p.get("upn", "")).split("@")[0].endswith(persona)
    )
    upn = entry["upn"]
    return PersonaCredential(persona, cfg["tenantId"], upn), upn


def _short(value: Any, limit: int = 600) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + f"... [{len(text)} chars]"


def show_items(response: Any) -> None:
    for item in response.output:
        kind = getattr(item, "type", "?")
        if kind == "mcp_list_tools":
            names = [t.name if hasattr(t, "name") else t.get("name") for t in (item.tools or [])]
            print(f"  [tools/list  ] {item.server_label}: {', '.join(names) if names else '(none)'}")
        elif kind == "mcp_call":
            status = "ERROR" if getattr(item, "error", None) else "ok"
            print(f"  [tools/call  ] {item.server_label}.{item.name}({_short(item.arguments, 200)}) -> {status}")
            body = item.error if getattr(item, "error", None) else getattr(item, "output", None)
            if body:
                print(f"                 {_short(body, 500)}")
        elif kind == "mcp_approval_request":
            print(f"  [approval    ] {item.server_label}.{item.name}({_short(item.arguments, 200)})")
        elif kind == "oauth_consent_request":
            print(f"  [consent     ] {getattr(item, 'server_label', '')} -> (sign-in link, {len(item.consent_link)} chars)")
        elif kind == "message":
            continue
        else:
            print(f"  [{kind:<12}]")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt")
    ap.add_argument("--agent", default="abw-wall-desk")
    ap.add_argument("--persona", help="priya|wes|tara|carla|ian (device-code sign-in); default = az CLI user")
    ap.add_argument("--approve", choices=["ask", "yes", "no"], default="ask", help="how to answer mcp_approval_request items")
    ap.add_argument("--no-wait", action="store_true", help="do not wait for OAuth consent; exit 3 when consent is needed")
    ap.add_argument("--open-consent", action="store_true", help="open each OAuth consent link in the default browser and keep polling until consent is complete")
    ap.add_argument("--consent-timeout", type=int, default=600, help="seconds to keep polling for consent (with --open-consent)")
    ap.add_argument("--poll", type=int, default=10, help="seconds between consent polls")
    ap.add_argument("--reopen", type=int, default=240, help="seconds before re-opening a still-pending consent link")
    ap.add_argument("--save", action="store_true", help="write a transcript to demo\\evidence")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()

    cred, who = build_credential(args.persona)
    project = AIProjectClient(endpoint=project_endpoint(), credential=cred)
    openai = project.get_openai_client()
    extra = {"agent_reference": {"name": args.agent, "type": "agent_reference"}}

    transcript: dict[str, Any] = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "agent": args.agent,
        "as": who,
        "prompt": args.prompt,
        "turns": [],
    }
    print(f"agent={args.agent}  as={who}\n> {args.prompt}")
    started = time.time()
    exit_code = 0
    response: Any = None
    failure: dict[str, Any] | None = None
    surfaced: dict[str, float] = {}
    last_note: dict[str, float] = {}
    consent_deadline = time.time() + args.consent_timeout

    def create(**kw: Any) -> Any:
        delay = 3.0
        for attempt in range(10):
            try:
                return openai.responses.create(extra_body=extra, **kw)
            except APIConnectionError as exc:
                if attempt == 9:
                    raise
                print(f"  [retry       ] network error ({type(exc.__cause__ or exc).__name__}); retrying in {delay:.0f}s")
                time.sleep(delay)
                delay = min(delay * 1.5, 15.0)
        raise RuntimeError("unreachable")

    try:
        response = create(input=args.prompt)
        for _round in range(400):
            if not args.quiet:
                show_items(response)
            transcript["turns"].append({"id": response.id, "items": [getattr(i, "type", "?") for i in response.output]})
            consent = [i for i in response.output if getattr(i, "type", "") == "oauth_consent_request"]
            approvals = [i for i in response.output if getattr(i, "type", "") == "mcp_approval_request"]
            if consent:
                now = time.time()
                for gone in [k for k in surfaced if k not in {getattr(c, "server_label", "") for c in consent}]:
                    print(f"  [consent     ] '{gone}' not pending in this pass (Foundry surfaces one consent at a time)")
                    surfaced.pop(gone, None)
                for c in consent:
                    label = getattr(c, "server_label", "")
                    if label not in surfaced or now - surfaced[label] > args.reopen:
                        again = label in surfaced
                        surfaced[label] = now
                        print(f"\n>>> OAuth consent needed for '{label}'{' (still pending - re-opening)' if again else ''}: sign in as {who} and allow.")
                        if args.open_consent:
                            webbrowser.open(c.consent_link)
                        else:
                            print(f"    {c.consent_link}")
                    elif now - last_note.get(label, 0) > 30:
                        last_note[label] = now
                        print(f"  [consent     ] waiting for '{label}' ({int(now - surfaced[label])}s)")
                if args.no_wait or not (args.open_consent or sys.stdin.isatty()) or time.time() > consent_deadline:
                    exit_code = 3
                    break
                if args.open_consent:
                    time.sleep(args.poll)
                else:
                    input("Open the link(s) as the same user, complete consent, then press Enter... ")
                # fresh response: continuing from previous_response_id would replay the stale, empty tool lists
                response = create(input=args.prompt)
                continue
            if approvals:
                answers = []
                for a in approvals:
                    if args.approve == "ask":
                        ok = input(f"Approve {a.server_label}.{a.name}({_short(a.arguments, 200)})? [y/N] ").strip().lower() == "y"
                    else:
                        ok = args.approve == "yes"
                    print(f"  -> approval {'GRANTED' if ok else 'DENIED'} for {a.name}")
                    answers.append({"type": "mcp_approval_response", "approve": ok, "approval_request_id": a.id})
                response = create(input=answers, previous_response_id=response.id)
                continue
            break
    except APIStatusError as exc:
        body = getattr(exc, "body", None) or {}
        err = body.get("error", body) if isinstance(body, dict) else {"message": str(body)}
        failure = {"http": exc.status_code, "code": err.get("code"), "message": err.get("message"), "request_id": err.get("request_id")}
        exit_code = 4
        print(f"\n!! Agent run failed: HTTP {exc.status_code} code={err.get('code')}")
        print(f"   {_short(err.get('message'), 1500)}")
    except CredentialUnavailableError as exc:
        failure = {"http": None, "code": "credential_unavailable", "message": str(exc).splitlines()[0], "request_id": None}
        exit_code = 5
        print("\n!! Could not get an Azure token for the agent call.")
        print(f"   {failure['message']}")
        print("   Check `az account show` (run `az login` if needed), wait for any other `az` command to finish, and retry.")

    text = (getattr(response, "output_text", "") or "") if response is not None else ""
    usage = getattr(response, "usage", None) if response is not None else None
    print(f"\n{text}\n")
    if usage:
        print(f"[tokens in={usage.input_tokens} out={usage.output_tokens}  {time.time() - started:.1f}s  response={response.id}]")
    transcript.update(
        {
            "answer": text,
            "response_id": getattr(response, "id", None),
            "status": getattr(response, "status", None) if failure is None else "failed",
            "failure": failure,
            "seconds": round(time.time() - started, 1),
        }
    )
    if args.save:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        out = EVIDENCE / f"{dt.datetime.now():%Y%m%d-%H%M%S}-{args.agent}-{(args.persona or 'operator')}.json"
        out.write_text(json.dumps(transcript, indent=2, default=str), encoding="utf-8")
        print(f"saved {out}")
    return exit_code


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    sys.exit(main())
