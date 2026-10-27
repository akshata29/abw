"""TOTP helper for the five demo personas.

A tenant that forces MFA for every user leaves each persona needing ONE manual authenticator-app enrolment (the first tenant this was built
in also blocked security-info (MFA) registration outside the Microsoft VPN/SAW ranges and had no Temporary Access Pass; the second enforces MFA
through Microsoft-managed Conditional Access). This helper stores the
base32 secret shown on that enrolment page and prints the current 6-digit code, so device-code sign-ins during the live demo are
one copy/paste instead of a phone hunt.

    python identity\\Persona-Totp.py login priya     # prints the UPN and puts the password on the clipboard (never printed; cleared in 60 s)
    python identity\\Persona-Totp.py set priya       # paste the base32 secret (input is hidden)
    python identity\\Persona-Totp.py code priya      # current code + seconds left (add --copy to put it on the clipboard)
    python identity\\Persona-Totp.py watch wes       # keep printing the code as it rolls (Ctrl+C to stop)
    python identity\\Persona-Totp.py list            # which personas have a stored secret
    python identity\\Persona-Totp.py selftest        # RFC 6238 test vectors

Secrets live in .secrets\\totp.json (git-ignored, same sensitivity as personas.json). Nothing but the 6-digit code is ever printed.
RFC 6238: HMAC-SHA1, 30 s step, 6 digits (what Microsoft Entra "different authenticator app" enrolment issues).
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import hmac
import json
import pathlib
import struct
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
STORE = ROOT / ".secrets" / "totp.json"
PERSONAS = ("priya", "wes", "tara", "carla", "ian")


def _key(b32: str) -> bytes:
    s = "".join(b32.split()).upper().rstrip("=")
    return base64.b32decode(s + "=" * (-len(s) % 8))


def totp(b32: str, at: float | None = None, digits: int = 6, step: int = 30) -> str:
    counter = int((time.time() if at is None else at) // step)
    mac = hmac.new(_key(b32), struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off : off + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return f"{code:0{digits}d}"


def _load() -> dict[str, str]:
    return json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else {}


def _persona(name: str) -> str:
    if name not in PERSONAS:
        raise SystemExit(f"unknown persona '{name}' (expected one of: {', '.join(PERSONAS)})")
    return name


def _secret_for(name: str) -> str:
    secret = _load().get(_persona(name))
    if not secret:
        raise SystemExit(f"no TOTP secret stored for {name}; run: python identity\\Persona-Totp.py set {name}")
    return secret


def _copy(text: str) -> None:
    subprocess.run(["clip"], input=text, text=True, check=False)


def cmd_set(name: str) -> None:
    raw = getpass.getpass(f"base32 secret for {_persona(name)} (hidden): ")
    try:
        _key(raw)
        totp(raw)
    except Exception as ex:  # noqa: BLE001
        raise SystemExit(f"that is not a valid base32 secret ({type(ex).__name__})") from ex
    data = _load()
    data[name] = "".join(raw.split()).upper()
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"stored. Enter this code on the enrolment page to verify it now: {totp(data[name])}")


def cmd_code(name: str, copy: bool) -> None:
    secret = _secret_for(name)
    left = 30 - int(time.time()) % 30
    code = totp(secret)
    print(f"{name}: {code}   ({left}s left)")
    if copy:
        _copy(code)
        print("copied to clipboard")


def cmd_watch(name: str) -> None:
    secret = _secret_for(name)
    last = ""
    try:
        while True:
            code = totp(secret)
            left = 30 - int(time.time()) % 30
            if code != last:
                print()
                last = code
            print(f"\r{name}: {code}   ({left:2d}s left)  ", end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print()


def cmd_login(name: str) -> None:
    path = ROOT / ".secrets" / "personas.json"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    entry = data[_persona(name)] if isinstance(data, dict) and name in data else next(
        p for p in data if str(p.get("upn", "")).split("@")[0].endswith(name)
    )
    print(f"{name}: sign in as {entry['upn']}")
    _copy(entry["password"])
    print("password copied to the clipboard (not printed); it is cleared again in 60 s")
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-Command", "Start-Sleep 60; Set-Clipboard -Value $null"],
            creationflags=0x08000000 | 0x00000200,  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP (a DETACHED_PROCESS cannot reach the clipboard)
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        print("could not schedule the clipboard clear - clear it yourself")


def cmd_list() -> None:
    data = _load()
    for p in PERSONAS:
        print(f"{p:6} {'secret stored' if p in data else 'NOT enrolled'}")


def cmd_selftest() -> None:
    ref = base64.b32encode(b"12345678901234567890").decode()
    vectors = [(59, "287082"), (1111111109, "081804"), (1111111111, "050471"), (1234567890, "005924"), (2000000000, "279037")]
    bad = [(t, want, totp(ref, at=t)) for t, want in vectors if totp(ref, at=t) != want]
    if bad:
        raise SystemExit(f"RFC 6238 vectors FAILED: {bad}")
    print(f"RFC 6238 vectors ok ({len(vectors)}/{len(vectors)})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("set", "code", "watch", "login"):
        p = sub.add_parser(c)
        p.add_argument("persona")
        if c == "code":
            p.add_argument("--copy", action="store_true")
    sub.add_parser("list")
    sub.add_parser("selftest")
    a = ap.parse_args()
    if a.cmd == "set":
        cmd_set(a.persona)
    elif a.cmd == "code":
        cmd_code(a.persona, a.copy)
    elif a.cmd == "watch":
        cmd_watch(a.persona)
    elif a.cmd == "login":
        cmd_login(a.persona)
    elif a.cmd == "list":
        cmd_list()
    else:
        cmd_selftest()


if __name__ == "__main__":
    sys.exit(main())
