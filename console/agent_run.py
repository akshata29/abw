"""Run one Foundry agent turn for the Demo Console and print one JSON event per line.

It is the same loop as src\\agent\\ask.py (create response -> show tool items -> answer approvals -> repeat), but
structured, so the console can draw tool calls, approval gates and guardrail stops without scraping text.
Approvals: with --approve ask it prints an `approval` event per request, then reads one JSON line per request from
stdin (`{"approve": true|false}`), in order. Nothing secret is printed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "agent"))
import ask  # noqa: E402  (build_credential; installs the DNS retry shim)
from abw_agents import load_state, project_endpoint  # noqa: E402
from azure.ai.projects import AIProjectClient  # noqa: E402
from azure.identity import CredentialUnavailableError  # noqa: E402
from openai import APIConnectionError, APIStatusError  # noqa: E402

DECISION = re.compile(r'"decision"\s*:\s*"([A-Za-z_]+)"')
REASON = re.compile(r'"reason"\s*:\s*"([^"]*)"')
REQUEST_ID = re.compile(r'"request_id"\s*:\s*"([0-9a-fA-F-]{8,})"')


def emit(kind: str, **data: Any) -> None:
    print(json.dumps({"type": kind, **data}, default=str), flush=True)


def _text(value: Any, limit: int = 1800) -> str:
    text = value if isinstance(value, str) else json.dumps(value, default=str)
    return text if len(text) <= limit else text[:limit] + f"... [{len(text)} chars]"


def show_items(response: Any) -> None:
    for item in response.output:
        kind = getattr(item, "type", "?")
        if kind == "mcp_list_tools":
            names = [t.name if hasattr(t, "name") else t.get("name") for t in (item.tools or [])]
            emit("tools", server=item.server_label, tools=names)
        elif kind == "mcp_call":
            error = getattr(item, "error", None)
            body = error if error else getattr(item, "output", None)
            text = _text(body or "", 1800)
            decision = DECISION.search(text)
            reason = REASON.search(text)
            rid = REQUEST_ID.search(text)
            emit(
                "call",
                server=item.server_label,
                tool=item.name,
                args=_text(item.arguments, 400),
                ok=not error,
                guardrail="returned no result" in text.lower(),
                body=text,
                decision=decision.group(1) if decision else None,
                reason=reason.group(1) if reason else None,
                request_id=rid.group(1) if rid else None,
            )
        elif kind == "oauth_consent_request":
            emit("consent", server=getattr(item, "server_label", ""), link=getattr(item, "consent_link", None))
        elif kind == "mcp_approval_request":
            continue


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="abw-wall-desk")
    ap.add_argument("--approve", choices=["ask", "yes", "no"], default="ask")
    ap.add_argument("--via", choices=["direct", "apim"], default=os.environ.get("ABW_AGENT_VIA", "direct"),
                    help="apim = the agent call enters through the APIM agent front door; direct = straight to the Foundry project endpoint")
    ap.add_argument("prompt")
    args = ap.parse_args()

    started = time.time()
    cred, who = ask.build_credential(None)
    emit("who", agent=args.agent, who=who, prompt=args.prompt, via=args.via)
    project = AIProjectClient(endpoint=project_endpoint(), credential=cred)
    openai = project.get_openai_client(base_url=load_state("frontdoor")["openAiBaseUrl"]) if args.via == "apim" else project.get_openai_client()
    extra = {"agent_reference": {"name": args.agent, "type": "agent_reference"}}
    totals: dict[str, Any] = {"in": 0, "out": 0, "rounds": 0, "gateway_ids": [], "consumed": 0, "remaining": None}

    def tally(raw: Any) -> Any:
        response = raw.parse()
        usage = getattr(response, "usage", None)
        totals["in"] += getattr(usage, "input_tokens", 0) or 0
        totals["out"] += getattr(usage, "output_tokens", 0) or 0
        totals["rounds"] += 1
        rid = raw.headers.get("x-abw-request-id")
        if rid and args.via == "apim":
            totals["gateway_ids"].append(rid)
        consumed = raw.headers.get("x-abw-tokens-consumed")
        if consumed and consumed.isdigit():
            totals["consumed"] += int(consumed)
        remaining = raw.headers.get("x-abw-tokens-remaining")
        if remaining and remaining.lstrip("-").isdigit():
            totals["remaining"] = int(remaining)
        return response

    def create(**kw: Any) -> Any:
        delay = 3.0
        for attempt in range(10):
            try:
                return tally(openai.responses.with_raw_response.create(extra_body=extra, **kw))
            except APIConnectionError as exc:
                if attempt == 9:
                    raise
                emit("retry", text=f"network blip ({type(exc.__cause__ or exc).__name__}); retrying in {delay:.0f}s")
                time.sleep(delay)
                delay = min(delay * 1.5, 15.0)
        raise RuntimeError("unreachable")

    response: Any = None
    exit_code = 0
    failure: dict[str, Any] | None = None
    try:
        response = create(input=args.prompt)
        for _round in range(60):
            show_items(response)
            consent = [i for i in response.output if getattr(i, "type", "") == "oauth_consent_request"]
            approvals = [i for i in response.output if getattr(i, "type", "") == "mcp_approval_request"]
            if consent:
                exit_code = 3
                break
            if not approvals:
                break
            for a in approvals:
                emit("approval", id=a.id, server=a.server_label, tool=a.name, args=_text(a.arguments, 400))
            answers = []
            for a in approvals:
                if args.approve == "ask":
                    line = sys.stdin.readline()
                    ok = bool(line) and bool(json.loads(line).get("approve"))
                else:
                    ok = args.approve == "yes"
                emit("approval_answer", id=a.id, tool=a.name, granted=ok)
                answers.append({"type": "mcp_approval_response", "approve": ok, "approval_request_id": a.id})
            response = create(input=answers, previous_response_id=response.id)
    except APIStatusError as exc:
        body = getattr(exc, "body", None) or {}
        err = body.get("error", body) if isinstance(body, dict) else {"message": str(body)}
        headers = getattr(exc.response, "headers", {}) or {}
        gateway_id = headers.get("x-abw-request-id")
        failure = {"http": exc.status_code, "code": err.get("code"), "message": _text(err.get("message") or "", 1500),
                   "request_id": err.get("request_id") or gateway_id, "via": args.via, "gateway_id": gateway_id,
                   "reason": err.get("reason"), "retry_after": headers.get("retry-after")}
        exit_code = 4
    except CredentialUnavailableError as exc:
        failure = {"http": None, "code": "credential_unavailable", "message": str(exc).splitlines()[0], "request_id": None}
        exit_code = 5
    except Exception as exc:  # surface anything else as a failure card instead of a stack trace
        failure = {"http": None, "code": type(exc).__name__, "message": _text(str(exc), 600), "request_id": None}
        exit_code = 6

    if failure:
        emit("failure", **failure)
    text = (getattr(response, "output_text", "") or "") if response is not None else ""
    err = getattr(response, "error", None) if response is not None else None
    incomplete = getattr(getattr(response, "incomplete_details", None), "reason", None) if response is not None else None
    emit(
        "final",
        answer=text,
        seconds=round(time.time() - started, 1),
        tokens_in=totals["in"] or None,
        tokens_out=totals["out"] or None,
        rounds=totals["rounds"],
        via=args.via,
        gateway_ids=totals["gateway_ids"],
        gateway_tokens=totals["consumed"] or None,
        tokens_remaining=totals["remaining"],
        response_id=getattr(response, "id", None),
        status=getattr(response, "status", None),
        incomplete=incomplete,
        error={"code": getattr(err, "code", None), "message": _text(getattr(err, "message", "") or "", 600)} if err else None,
        exit_code=exit_code,
    )
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
