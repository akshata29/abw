"""Make a shareable copy of the proof evidence.

`demo\\evidence\\` holds tenant, subscription, user, application and request identifiers. This script writes
`demo\\evidence-scrubbed\\` with the same files and the identifiers replaced, so the scoreboard and the proof
output can be shown or committed without exposing the lab tenant.

What is replaced
- every GUID becomes a stable pseudonym (uuid5 of the original under a fixed namespace), so one id maps to the
  same pseudonym in every file and cross-references still line up;
- the tenant's onmicrosoft.com domain, the resource-name suffix (u4), the Container Apps environment domain and
  public IPv4 addresses (read from infra\\generated\\config.json when it exists, plus generic patterns);
- JWT-looking strings.

What is kept: public Microsoft ids (first-party app ids, built-in role and policy definition ids) and the
fictional firm's names. Hidden state files (.prove-state.json) are not copied.

    python demo\\scrub_evidence.py [--src demo\\evidence] [--dest demo\\evidence-scrubbed]

Ends with a leak check over the output and exits 1 if an original identifier survived.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import logging
import re
import shutil
import sys
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
NAMESPACE = uuid.UUID("5b0f7a6e-2c1d-4e7a-9a3b-1f6d8c0a4e11")
KEEP_AFTER = ("roledefinitions/", "policydefinitions/", "policysetdefinitions/")
PUBLIC_IDS = {
    "04b07795-8ddb-461a-bbee-02f9e1bf7b46",  # Azure CLI
    "1950a258-227b-4e31-a9cf-717495945fc2",  # Azure PowerShell
    "00000003-0000-0000-c000-000000000000",  # Microsoft Graph
    "00000002-0000-0000-c000-000000000000",  # Azure AD Graph
    "797f4846-ba00-4fd7-ba43-dac1f8f63013",  # Azure Service Management API
    "e406a681-f3d4-42a8-90b6-c2b029497af1",  # Azure Storage
    "cfa8b339-82a2-471a-a3c9-0fc0be7a4093",  # Azure Key Vault
}
DOMAIN = re.compile(r"[A-Za-z0-9-]+\.onmicrosoft\.com", re.I)
ACA_ENV = re.compile(r"[a-z0-9]+-[0-9a-f]{8}(?=\.[a-z0-9]+\.azurecontainerapps\.io)", re.I)
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
JWT = re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]*")


class Scrubber:
    def __init__(self, literals: dict[str, str]) -> None:
        self.literals = literals
        self.originals: set[str] = set()
        self.ips: dict[str, str] = {}
        self.guid_count = 0

    def _guid(self, m: re.Match[str]) -> str:
        g = m.group(0)
        low = g.lower()
        if low in PUBLIC_IDS:
            return g
        if m.string[max(0, m.start() - 40):m.start()].lower().endswith(KEEP_AFTER):
            return g
        self.originals.add(low)
        self.guid_count += 1
        pseudo = str(uuid.uuid5(NAMESPACE, low))
        return pseudo.upper() if g.isupper() else pseudo

    def _ip(self, m: re.Match[str]) -> str:
        raw = m.group(0)
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError:
            return raw
        if not ip.is_global:
            return raw
        self.originals.add(raw)
        return self.ips.setdefault(raw, f"203.0.113.{len(self.ips) + 10}")

    def text(self, s: str) -> str:
        for needle, repl in self.literals.items():
            s = re.sub(re.escape(needle), repl, s, flags=re.I)
        s = DOMAIN.sub("contoso-lab.onmicrosoft.com", s)
        s = ACA_ENV.sub("env-00000000", s)
        s = JWT.sub("<jwt-redacted>", s)
        s = GUID.sub(self._guid, s)
        return IPV4.sub(self._ip, s)


def _literals() -> dict[str, str]:
    cfg = ROOT / "infra" / "generated" / "config.json"
    out: dict[str, str] = {}
    if not cfg.exists():
        logger.warning("infra\\generated\\config.json not found: using generic patterns only")
        return out
    d = json.loads(cfg.read_text(encoding="utf-8"))
    if d.get("tenantDomain"):
        out[d["tenantDomain"]] = "contoso-lab.onmicrosoft.com"
    if d.get("u4"):
        out[d["u4"]] = "xxxx"
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", default=str(ROOT / "demo" / "evidence"))
    ap.add_argument("--dest", default=str(ROOT / "demo" / "evidence-scrubbed"))
    args = ap.parse_args()
    src, dest = Path(args.src), Path(args.dest)
    if not src.is_dir():
        print(f"no evidence folder at {src}")
        return 2

    lit = _literals()
    sc = Scrubber(lit)
    if dest.exists():
        shutil.rmtree(dest)
    written: list[Path] = []
    for f in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = f.relative_to(src)
        if any(part.startswith(".") for part in rel.parts) or f.suffix == ".tmp":
            continue
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        body = sc.text(f.read_text(encoding="utf-8", errors="replace"))
        if f.suffix == ".json":
            json.loads(body)
        out.write_text(body, encoding="utf-8")
        written.append(out)

    (dest / "README.md").write_text(
        "# Scrubbed evidence\n\nCopy of `demo\\evidence\\` produced by `python demo\\scrub_evidence.py`. "
        "GUIDs are replaced by stable pseudonyms (the same id maps to the same pseudonym in every file), "
        "the tenant domain by `contoso-lab.onmicrosoft.com`, the resource-name suffix by `xxxx`, and public IPs by "
        "documentation addresses. Public Microsoft ids (first-party apps, built-in role and policy definitions) are kept. "
        "All data in the demo is synthetic.\n",
        encoding="utf-8")

    leaks: list[str] = []
    blob = "\n".join(p.read_text(encoding="utf-8") for p in written)
    low = blob.lower()
    for original in sorted(sc.originals):
        if original in low:
            leaks.append(original)
    for needle in lit:
        if needle.lower() in low:
            leaks.append(f"<{len(needle)}-char literal>")
    if JWT.search(blob):
        leaks.append("<jwt>")

    print(f"scrubbed {len(written)} files -> {dest}")
    print(f"  GUID occurrences replaced: {sc.guid_count} ({len(sc.originals)} distinct ids/IPs)")
    print(f"  literals replaced: {len(lit)} · public IPs mapped: {len(sc.ips)}")
    if leaks:
        print(f"LEAK CHECK FAILED: {len(leaks)} original value(s) survived")
        return 1
    print("  leak check: clean")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    sys.exit(main())
