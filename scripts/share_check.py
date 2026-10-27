"""Share-readiness check for the Agents Behind the Wall repository.

A deployed checkout holds the identifiers and secrets of the tenant it was deployed to: infra/generated, .secrets, raw proof evidence,
screenshots. Before the folder is zipped, pushed or e-mailed, run this tool.

    python scripts/share_check.py scan                      # look for this deployment's own values in every shareable file
    python scripts/share_check.py scan --show               # same, and print each hit line with the value masked as <kind>
    python scripts/share_check.py export <target-dir>       # copy a share-safe tree (private paths left out), then scan the copy
    python scripts/share_check.py scan --term "Contoso"     # extra words to look for (case-insensitive), repeatable

How it works: it learns the values that belong to THIS deployment (infra/generated/*.json, an archived earlier state in _archive/ if present,
.secrets/*) and looks for exactly those values in the shareable files. There is no pattern guessing for ids, so public GUIDs (built-in role
ids, first-party application ids) do not produce noise. Values are NEVER printed: a hit shows the file, the line number and the kind only.
Values that identify nobody (generic words such as an owner tag of "admin", plain URLs, numbers, public tool manifests) are not hunted, and an
owner alias is matched as a whole word only.

Exit code 0 = nothing found, 1 = at least one hit (or a copy problem). Standard library only.
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Never part of a share: state, secrets, caches, raw evidence, rendered deck artefacts.
PRIVATE_DIRS = [".git", ".secrets", ".venv", "_archive", "__pycache__", ".pytest_cache", "node_modules",
                "infra/generated", "demo/evidence", "deck/png", "deck/screens"]
PRIVATE_FILE_GLOBS = [".env", ".env.*", "*.local.json", "*.pyc", "deck/*.pdf", "console/.state.json"]
KEEP_EMPTY = ["infra/generated/.gitkeep", "demo/evidence/.gitkeep"]

TEXT_EXT = {".py", ".ps1", ".psm1", ".bicep", ".bicepparam", ".json", ".xml", ".kql", ".md", ".txt", ".url", ".svg", ".csv", ".yml", ".yaml",
            ".toml", ".cfg", ".ini", ".bat", ".sh", ".js", ".css", ".html", ".excalidraw", ".gitignore", ".gitkeep", ".log", ".workbook", ""}
ZIP_EXT = {".pptx", ".docx", ".xlsx"}

# Public identifiers that may show up in generated state and are not secrets (lowercase).
PUBLIC_VALUES = {
    "04b07795-8ddb-461a-bbee-02f9e1bf7b46",  # Azure CLI first-party client
    "1950a258-227b-4e31-a9cf-717495945fc2",  # Azure PowerShell first-party client
    "f8cdef31-a31e-4b4a-93e4-5f571e91255a",  # Microsoft Services tenant (first-party app lookups)
    "00000003-0000-0000-c000-000000000000",  # Microsoft Graph
    "00000002-0000-0000-c000-000000000000",  # Azure AD Graph
    "797f4846-ba00-4fd7-ba43-dac1f8f63013",  # Azure Service Management API
    "e406a681-f3d4-42a8-90b6-c2b029497af1",  # Azure Storage
    "cfa8b339-82a2-471a-a3c9-0fc0be7a4093",  # Azure Key Vault
    "9ec59623-ce40-4dc8-a635-ed0275b5d58a",  # Microsoft Purview first-party app
    "849de3f8-3686-489c-bd02-732984d0c145",  # built-in role definition: A365 Gateway Policy Operator
    "1.0.0.0",  # ARM deployment contentVersion, which reads as an IPv4 address
    "00000000-0000-0000-0000-000000000000",
}
# Placeholder domains: the one demo\scrub_evidence.py writes, and the documentation domains reserved by RFC 2606.
PUBLIC_EMAIL_DOMAINS = {"contoso-lab.onmicrosoft.com", "example.com", "example.org", "example.net"}

GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
IPV4 = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")

# Noise control. A value that identifies nobody is not hunted: an owner tag of "admin" must not flag "Administrator", and a stored
# word such as "environment" or a plain URL is documentation text, not a secret. A key that says it holds a secret is always trusted.
GENERIC_WORDS = {"admin", "administrator", "owner", "user", "users", "demo", "test", "azure", "microsoft", "contoso", "default", "root",
                 "operator"}
SECRET_KEY_NAME = re.compile(r"^(?:client_?)?(?:secret|password|passwd|pwd|passphrase|totp_?seed|seed|api_?key|access_?key|account_?key|shared_?key|"
                             r"primary_?key|secondary_?key|subscription_?key|private_?key|access_?token|refresh_?token|id_?token|token|"
                             r"sas_?token|connection_?string|key)$", re.I)
PLAIN_TEXT = re.compile(r"^[A-Za-z][A-Za-z .,:;_/'()\-]*$")
# A hyphenated lowercase resource name such as a VM or NIC name. Under a key that does not say "secret" it identifies nobody.
RESOURCE_NAME = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+){2,}$")
PLAIN_URL = re.compile(r"^https?://[^\s?@#]*$", re.I)
DIGITS_ONLY = re.compile(r"^\d+$")
# Tool state kept next to the secrets that is public by construction (azd extension manifests).
PUBLIC_SECRET_SUBDIRS = {"extensions", "telemetry"}


def _leaves(node):
    if isinstance(node, dict):
        for v in node.values():
            yield from _leaves(v)
    elif isinstance(node, list):
        for v in node:
            yield from _leaves(v)
    elif isinstance(node, str):
        yield node


def _leaf_items(node, key: str = ""):
    """Like _leaves, but yields (nearest key name, value) so the key can say whether the value is a secret."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _leaf_items(v, str(k))
    elif isinstance(node, list):
        for v in node:
            yield from _leaf_items(v, key)
    elif isinstance(node, str):
        yield key, node


def secret_shaped(key: str, value: str, allow: set[str]) -> bool:
    """True when a value stored under .secrets is worth looking for in shareable files."""
    v = value.strip()
    if len(v) < 8 or v.lower() in allow:
        return False
    if SECRET_KEY_NAME.match(key):
        return True
    return not (PLAIN_TEXT.match(v) or PLAIN_URL.match(v) or DIGITS_ONLY.match(v) or RESOURCE_NAME.match(v))


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None


def _is_private_ip(s: str) -> bool:
    a = [int(x) for x in s.split(".")]
    return a[0] in (10, 127, 0) or (a[0] == 192 and a[1] == 168) or (a[0] == 172 and 16 <= a[1] <= 31) or any(x > 255 for x in a)


def classify_state_value(s: str, allow: set[str]) -> str | None:
    s = s.strip()
    if len(s) < 6 or s.lower() in allow:
        return None
    if GUID.match(s):
        return "guid"
    if EMAIL.match(s):
        return None if s.rsplit("@", 1)[1].lower() in PUBLIC_EMAIL_DOMAINS else "email"
    if IPV4.match(s):
        return None if _is_private_ip(s) else "ip"
    if s.lower().startswith("/subscriptions/"):
        return "resource-id"
    if "instrumentationkey=" in s.lower() or "sharedaccesskey=" in s.lower() or "accountkey=" in s.lower():
        return "connection-string"
    return None


class Sensitive:
    """Values that belong to this deployment, split by how they are matched."""

    def __init__(self) -> None:
        self.insensitive: dict[str, str] = {}   # value (lowercase) -> kind
        self.sensitive: dict[str, str] = {}     # value (exact) -> kind
        self.words: dict[str, str] = {}         # value (lowercase), matched only as a whole word -> kind

    def add(self, value: str, kind: str, exact: bool = False, word: bool = False) -> None:
        if not value:
            return
        if word:
            self.words[value.lower()] = kind
        elif exact:
            self.sensitive[value] = kind
        else:
            self.insensitive[value.lower()] = kind

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for k in list(self.insensitive.values()) + list(self.sensitive.values()) + list(self.words.values()):
            out[k] = out.get(k, 0) + 1
        return out

    def compile(self):
        ci = re.compile("|".join(re.escape(v) for v in sorted(self.insensitive, key=len, reverse=True)), re.I) if self.insensitive else None
        cs = re.compile("|".join(re.escape(v) for v in sorted(self.sensitive, key=len, reverse=True))) if self.sensitive else None
        cw = re.compile(r"(?<![A-Za-z0-9])(?:" + "|".join(re.escape(v) for v in sorted(self.words, key=len, reverse=True)) + r")(?![A-Za-z0-9])",
                        re.I) if self.words else None
        return ci, cs, cw


def load_sensitive(root: Path, extra_terms: list[str], extra_allow: list[str], use_archive: bool = True) -> Sensitive:
    allow = set(PUBLIC_VALUES) | {a.lower() for a in extra_allow}
    sens = Sensitive()

    state_files = sorted((root / "infra" / "generated").glob("*.json"))
    if use_archive and (root / "_archive").exists():
        state_files += sorted((root / "_archive").rglob("*.json"))
    for f in state_files:
        data = _read_json(f)
        if data is None:
            continue
        for leaf in _leaves(data):
            kind = classify_state_value(leaf, allow)
            if kind:
                sens.add(leaf.strip(), kind)

    cfg = _read_json(root / "infra" / "generated" / "config.json") or {}
    for key in ("u4",):
        v = str(cfg.get(key) or "")
        if len(v) >= 4:
            sens.add(v, "unique-suffix")
    dom = str(cfg.get("tenantDomain") or "")
    if dom:
        sens.add(dom, "tenant-domain")
        first = dom.split(".")[0]
        if len(first) >= 5:
            sens.add(first, "tenant-name")
    owner = str((cfg.get("tags") or {}).get("owner") or "")
    if len(owner) >= 4 and owner.lower() not in GENERIC_WORDS:
        sens.add(owner, "owner-alias", word=True)
    for key in ("operatorUpn", "alertEmail", "publisherEmail"):
        v = str(cfg.get(key) or "")
        if v:
            sens.add(v, "email")
    ws = str(cfg.get("entraWorkspaceId") or "")
    if ws:
        sens.add(ws, "resource-id")
        sens.add(ws.rstrip("/").split("/")[-1], "workspace-name")

    secrets = root / ".secrets"
    if secrets.exists():
        for f in secrets.rglob("*"):
            if not f.is_file() or f.stat().st_size > 2_000_000:
                continue
            if PUBLIC_SECRET_SUBDIRS & set(f.relative_to(secrets).parts[:-1]):
                continue
            if f.suffix.lower() == ".json":
                data = _read_json(f)
                if data is not None:
                    for key, leaf in _leaf_items(data):
                        if secret_shaped(key, leaf, allow):
                            sens.add(leaf, "secret", exact=True)
            elif f.suffix.lower() in (".txt", ".key", ".pwd"):
                try:
                    t = f.read_text(encoding="utf-8-sig").strip()
                except Exception:
                    continue
                if len(t) >= 12:
                    sens.add(t, "secret", exact=True)

    for t in extra_terms:
        if t.strip():
            sens.add(t.strip(), "term")
    return sens


def is_private(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    parts = rel.split("/")
    for d in PRIVATE_DIRS:
        dp = d.split("/")
        if parts[: len(dp)] == dp:
            return True
    name = parts[-1]
    for g in PRIVATE_FILE_GLOBS:
        if fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(name, g):
            return True
    return False


def iter_shareable(base: Path):
    if base.is_file():
        yield base, base.name
        return
    for p in sorted(base.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(base).as_posix()
        if is_private(rel):
            continue
        yield p, rel


def _texts(path: Path):
    """Yield (label, text) chunks for a file; None when the file is binary and cannot be read."""
    ext = path.suffix.lower()
    if ext in ZIP_EXT:
        try:
            with zipfile.ZipFile(path) as z:
                for n in z.namelist():
                    if n.lower().endswith((".xml", ".rels", ".txt", ".json")):
                        yield n, z.read(n).decode("utf-8", errors="ignore")
        except Exception:
            yield None, None
        return
    if ext not in TEXT_EXT:
        yield None, None
        return
    try:
        yield "", path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        yield None, None


def mask_line(line: str, sens: Sensitive, patterns) -> str:
    """The line with every learned value replaced by <kind>, so a hit can be fixed without printing the value."""
    ci, cs, cw = patterns
    if ci:
        line = ci.sub(lambda m: f"<{sens.insensitive[m.group(0).lower()]}>", line)
    if cs:
        line = cs.sub(lambda m: f"<{sens.sensitive[m.group(0)]}>", line)
    if cw:
        line = cw.sub(lambda m: f"<{sens.words[m.group(0).lower()]}>", line)
    return line


def scan_tree(base: Path, sens: Sensitive, quiet: bool = False, show: bool = False) -> tuple[int, int, int]:
    patterns = sens.compile()
    ci, cs, cw = patterns
    files = hits = skipped = 0
    for path, rel in iter_shareable(base):
        file_hits: list[tuple[str, int, str]] = []
        masked: dict[tuple[str, int], str] = {}
        for label, text in _texts(path):
            if text is None:
                skipped += 1
                if not quiet:
                    print(f"  not scanned (binary): {rel}")
                continue
            for lineno, line in enumerate(text.splitlines(), 1):
                kinds = set()
                if ci:
                    for m in ci.finditer(line):
                        kinds.add(sens.insensitive[m.group(0).lower()])
                if cs:
                    for m in cs.finditer(line):
                        kinds.add(sens.sensitive[m.group(0)])
                if cw:
                    for m in cw.finditer(line):
                        kinds.add(sens.words[m.group(0).lower()])
                for k in kinds:
                    file_hits.append((label, lineno, k))
                if kinds and show:
                    masked[(label, lineno)] = mask_line(line, sens, patterns).strip()[:240]
        files += 1
        if file_hits:
            hits += len(file_hits)
            summary = ", ".join(f"{(l + ':') if l else ''}{n}[{k}]" for l, n, k in file_hits[:12])
            more = f" (+{len(file_hits) - 12} more)" if len(file_hits) > 12 else ""
            print(f"LEAK  {rel}  {summary}{more}")
            for (label, lineno), text in masked.items():
                safe = text.encode("ascii", "replace").decode("ascii")
                print(f"      {(label + ':') if label else ''}{lineno}: {safe}")
    return files, hits, skipped


def export_tree(src: Path, dst: Path, force: bool) -> int:
    if dst.exists() and any(dst.iterdir()):
        if not force:
            print(f"target {dst} is not empty; use --force to replace it", file=sys.stderr)
            return -1
        shutil.rmtree(dst)
    dst.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path, rel in iter_shareable(src):
        out = dst / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)
        copied += 1
    for keep in KEEP_EMPTY:
        k = dst / keep
        k.parent.mkdir(parents=True, exist_ok=True)
        k.touch()
    return copied


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("scan", "export"):
        p = sub.add_parser(name)
        p.add_argument("--term", action="append", default=[], help="extra word to look for (case-insensitive); repeatable")
        p.add_argument("--allow", action="append", default=[], help="public value to ignore (an id you have checked is not private); repeatable")
        p.add_argument("--no-archive", action="store_true", help="do not learn values from _archive/")
        if name == "scan":
            p.add_argument("path", nargs="?", default=None, help="file or folder to scan (default: this repository)")
            p.add_argument("--show", action="store_true", help="also print each hit line with the value replaced by <kind> (the value is never printed)")
        else:
            p.add_argument("target", help="folder to create (must be empty or missing)")
            p.add_argument("--force", action="store_true", help="replace the target folder if it exists")
    args = ap.parse_args()

    sens = load_sensitive(ROOT, args.term, args.allow, use_archive=not args.no_archive)
    c = sens.counts()
    known = ", ".join(f"{k} {v}" for k, v in sorted(c.items())) or "none"
    print(f"learned {sum(c.values())} deployment-specific values ({known})")
    if sum(c.values()) == 0 and not args.term:
        print("note: no infra/generated or .secrets state found here, so only --term words can be checked")

    if args.cmd == "scan":
        base = Path(args.path).resolve() if args.path else ROOT
        files, hits, skipped = scan_tree(base, sens, show=args.show)
    else:
        dst = Path(args.target).resolve()
        if dst == ROOT or ROOT in dst.parents:
            print("the target must be outside the repository", file=sys.stderr)
            return 2
        copied = export_tree(ROOT, dst, args.force)
        if copied < 0:
            return 2
        print(f"copied {copied} files to {dst} (private paths left out)")
        files, hits, skipped = scan_tree(dst, sens)
        base = dst

    print(f"scanned {files} files under {base}; {hits} hit(s); {skipped} binary file(s) not scanned")
    if hits:
        print("FAIL: remove or replace the values above (they are not printed on purpose), then run again.")
        return 1
    print("OK: none of this deployment's own values were found in the shareable files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
