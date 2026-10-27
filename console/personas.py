"""Persona switcher for the Demo Console - real Entra users for the raw gateway beats.

The default caller is the *operator* (the signed-in admin, who mirrors Wes + Tara). A persona is one of the five demo users, who
signs in ONCE with the device-code flow against the gateway test client (`abw-test-client`: a public client with tenant-wide
consent for the five MCP APIs). The refresh token is cached in `.secrets\\msal-test-<id>.json` - the same file the CLI uses
(`demo\\mcpclient.persona_token`, `abw-gw ... -Persona <id>`) - so a sign-in done here also works in a terminal and vice versa.

Rules: a job thread only ever asks for tokens *silently* (`token` raises `NeedsSignIn` instead of waiting on a prompt); the sign-in
itself runs on its own cancellable thread and refuses to save a sign-in made by the wrong account; and nothing secret leaves this
module except the six-digit one-time code the presenter asks for. Passwords and TOTP seeds stay in `.secrets\\` and are only copied
to the clipboard (and wiped from it again), never returned or logged.
"""
from __future__ import annotations

import base64
import contextlib
import functools
import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import msal

import mcpclient

log = logging.getLogger(__name__)

ROOT = mcpclient.ROOT
SECRETS = ROOT / ".secrets"
TOTP_STORE = SECRETS / "totp.json"
PASSWORD_STORE = SECRETS / "personas.json"

IDS = ("priya", "wes", "tara", "carla", "ian")
SERVERS = ("research", "wall", "actions", "private", "vendor")
OPERATOR_LABEL = "Operator (Wes + Tara)"
OPERATOR_STORY = "The signed-in admin, mirroring Wes + Tara: wall-crossed on Falcon only, can trade, reads firm positions. Agent beats always run as the operator."
DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP (a browser outlives the console)

# What each persona is expected to see at the wall. `verify` shows the real token roles next to this.
STORY = {
    "priya": "No wall crossing. Reads research and vendor quotes; the gateway refuses Falcon, Orion, trades and positions.",
    "wes": "Wall-crossed on Project Falcon only: Falcon allowed, Orion refused by the tool. No trading, no firm positions.",
    "tara": "Trader: can place orders (restricted names are still refused) and read firm positions. Not wall-crossed, so Falcon is refused.",
    "carla": "Compliance: wall-crossed on Falcon, reads trade history and firm positions, cannot trade. Orion is still refused.",
    "ian": "Information security: holds no data role at all, so the gateway refuses every tool call even with a valid token. He reads the audit trail, not the data.",
}


class NeedsSignIn(RuntimeError):
    """A persona has no usable cached sign-in. The message is written for the presenter and is shown as-is."""

    def __init__(self, persona: str, message: str) -> None:
        super().__init__(message)
        self.persona = persona


# ------------------------------------------------------------------------------------------------------- registry
def _check(pid: str) -> str:
    if pid not in IDS:
        raise ValueError("Unknown persona.")
    return pid


def _user(pid: str) -> dict[str, Any]:
    return mcpclient.ENTRA.get("users", {}).get(pid) or {}


def upn(pid: str) -> str:
    return str(_user(_check(pid)).get("upn", ""))


def name(pid: str) -> str:
    return re.sub(r"\s*\(ABW\)\s*$", "", str(_user(pid).get("display") or pid.title()))


def label(pid: str) -> str:
    job = str(_user(pid).get("job") or "")
    return f"{name(pid)} ({job})" if job else name(pid)


def role_pairs(pid: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for item in _user(pid).get("roles", []) or []:
        server, _, role = str(item).partition(":")
        pairs.append((server, role))
    return pairs


def can_use(pid: str, server: str) -> bool:
    """True when the persona holds at least one app role on that MCP server (without one the gateway refuses every call)."""
    api = mcpclient.API_KEY_FOR_SERVER.get(server)
    return any(s == api for s, _ in role_pairs(pid))


# --------------------------------------------------------------------------------------------------- token cache
def _cache_path(pid: str) -> Path:
    return SECRETS / f"msal-test-{pid}.json"


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _new_app(cache: msal.SerializableTokenCache) -> msal.PublicClientApplication:
    return msal.PublicClientApplication(
        mcpclient.ENTRA["clients"]["test"]["appId"], authority=f"https://login.microsoftonline.com/{mcpclient.TENANT}", token_cache=cache
    )


class _Slot:
    """In-memory MSAL app + cache for one persona. Rebuilt when the cache file changes on disk (the CLI shares it)."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.app: msal.PublicClientApplication | None = None
        self.cache: msal.SerializableTokenCache | None = None
        self.mtime = -1.0


_slots = {pid: _Slot() for pid in IDS}
_fresh: set[tuple[str, str, str]] = set()
_peek_memo: dict[str, tuple[float, bool]] = {}


def _load(pid: str) -> tuple[msal.PublicClientApplication, msal.SerializableTokenCache]:
    slot = _slots[pid]
    path = _cache_path(pid)
    mtime = _mtime(path)
    if slot.app is None or slot.cache is None or mtime != slot.mtime:
        cache = msal.SerializableTokenCache()
        if path.exists():
            cache.deserialize(path.read_text(encoding="utf-8"))
        slot.cache, slot.app, slot.mtime = cache, _new_app(cache), mtime
    return slot.app, slot.cache


def _persist(pid: str) -> None:
    slot = _slots[pid]
    if slot.cache is not None and slot.cache.has_state_changed:
        _atomic_write(_cache_path(pid), slot.cache.serialize())
        slot.cache.has_state_changed = False
        slot.mtime = _mtime(_cache_path(pid))


def forget() -> None:
    """Next token per (persona, server, scope) is forced fresh again - called by the console's Reset."""
    _fresh.clear()


def signed_in(pid: str) -> bool:
    """Cheap, offline: does the cache hold an account for this persona? (`verify` is the live check.)"""
    _check(pid)
    path = _cache_path(pid)
    mtime = _mtime(path)
    memo = _peek_memo.get(pid)
    if memo and memo[0] == mtime:
        return memo[1]
    found = False
    if mtime:
        try:
            cache = msal.SerializableTokenCache()
            cache.deserialize(path.read_text(encoding="utf-8"))
            want = upn(pid).lower()
            found = any(str(a.get("username", "")).lower() == want for a in cache.find(msal.TokenCache.CredentialType.ACCOUNT))
        except (OSError, ValueError):
            found = False
    _peek_memo[pid] = (mtime, found)
    return found


def token(pid: str, server: str, scope: str = "Tools.Read") -> str:
    """A persona's delegated token (azp = the gateway test client), silently. Never prompts: raises `NeedsSignIn` instead.

    The first token per (persona, server, scope) after the console starts is forced fresh so the role claims are current.
    """
    _check(pid)
    slot = _slots[pid]
    with slot.lock:
        app, _ = _load(pid)
        accounts = app.get_accounts(username=upn(pid))
        if not accounts:
            raise NeedsSignIn(pid, f"{name(pid)} has not signed in yet. Open Acting as (top of the left rail, or press P), press Sign in and finish the code once - it takes about a minute after MFA is enrolled.")
        key = (pid, server, scope)
        res = app.acquire_token_silent([mcpclient.scope_for(server, scope)], account=accounts[0], force_refresh=key not in _fresh)
        _persist(pid)
        if not res or "access_token" not in res:
            why = str((res or {}).get("error") or "no refresh token")
            raise NeedsSignIn(pid, f"{name(pid)}'s sign-in has expired or was revoked ({why}). Open Acting as (press P) and sign in again.")
        _fresh.add(key)
        return str(res["access_token"])


def verify(pid: str) -> dict[str, Any]:
    """Live proof of a persona's sign-in: a silent token for every MCP API and the (non-secret) claims inside it."""
    out: dict[str, Any] = {}
    who: dict[str, Any] = {}
    for server in SERVERS:
        try:
            summary = mcpclient.summarize(token(pid, server, "Tools.Read"))
        except NeedsSignIn:
            raise
        except Exception as exc:  # noqa: BLE001 - one API failing must not hide the others
            out[server] = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}
            continue
        who = who or {"upn": summary.get("upn") or summary.get("preferred_username"), "oid": summary.get("oid"), "azp": summary.get("azp")}
        out[server] = {"ok": True, "roles": summary.get("roles") or [], "scp": summary.get("scp"), "exp": summary.get("exp")}
    return {"persona": pid, "label": label(pid), "who": who, "servers": out, "checkedAt": time.time()}


# ------------------------------------------------------------------------------------------- device-code sign-in
_logins: dict[str, dict[str, Any]] = {}
_login_lock = threading.Lock()


def _finish(st: dict[str, Any], state: str, error: str = "") -> None:
    st.update(state=state, error=error, finished=time.time())


def start_login(pid: str) -> dict[str, Any]:
    """Begin a device-code sign-in. Returns the code to type at microsoft.com/devicelogin; a worker thread waits for it."""
    _check(pid)
    with _login_lock:
        current = _logins.get(pid)
        if current and current["state"] == "pending" and time.time() < current["flow"].get("expires_at", 0):
            return login_view(pid) or {}
        cache = msal.SerializableTokenCache()
        path = _cache_path(pid)
        if path.exists():
            cache.deserialize(path.read_text(encoding="utf-8"))
        app = _new_app(cache)
        flow = app.initiate_device_flow(scopes=[mcpclient.scope_for("research", "Tools.Read")])
        if "user_code" not in flow:
            raise RuntimeError(f"Entra did not start a device sign-in: {flow.get('error')}: {str(flow.get('error_description') or '')[:200]}")
        st: dict[str, Any] = {"state": "pending", "flow": flow, "started": time.time(), "error": "", "finished": 0.0}
        _logins[pid] = st
        threading.Thread(target=_login_worker, args=(pid, app, cache, st), daemon=True, name=f"persona-login-{pid}").start()
        log.info("persona %s: device sign-in started", pid)
        return login_view(pid) or {}


def _login_worker(pid: str, app: msal.PublicClientApplication, cache: msal.SerializableTokenCache, st: dict[str, Any]) -> None:
    flow = st["flow"]
    try:
        res = app.acquire_token_by_device_flow(flow)
    except Exception as exc:  # noqa: BLE001 - network blip or MSAL error: report it on the panel
        if st["state"] == "pending":
            _finish(st, "failed", f"{type(exc).__name__}: {str(exc)[:160]}")
        return
    if st["state"] != "pending":
        return
    if "access_token" not in res:
        code = str(res.get("error") or "")
        if time.time() >= flow.get("expires_at", 0) or code in ("authorization_pending", "expired_token", "code_expired"):
            _finish(st, "expired", "The code expired before anyone finished signing in. Press Sign in for a new one.")
        else:
            _finish(st, "failed", f"{code}: {str(res.get('error_description') or '')[:200]}")
        return
    claims = res.get("id_token_claims") or {}
    who = str(claims.get("preferred_username") or claims.get("upn") or "").lower()
    want = upn(pid).lower()
    if who != want:
        _finish(st, "failed", f"That sign-in was {who or 'a different account'}, not {want}. Nothing was saved. Close the private window, press Sign in again and sign in as {want}.")
        log.warning("persona %s: sign-in by a different account was rejected", pid)
        return
    slot = _slots[pid]
    with slot.lock:
        _atomic_write(_cache_path(pid), cache.serialize())
        slot.app = None
    _peek_memo.pop(pid, None)
    _finish(st, "ok")
    log.info("persona %s: signed in", pid)


def cancel_login(pid: str) -> None:
    _check(pid)
    with _login_lock:
        st = _logins.get(pid)
        if st and st["state"] == "pending":
            st["flow"]["expires_at"] = 0  # MSAL's documented way to stop the polling loop
            _finish(st, "cancelled")


def login_view(pid: str) -> dict[str, Any] | None:
    st = _logins.get(pid)
    if not st:
        return None
    flow = st["flow"]
    state = st["state"]
    left = max(0, int(flow.get("expires_at", 0) - time.time()))
    if state == "pending" and left == 0:
        state = "expired"
    if state != "pending" and st.get("finished") and time.time() - st["finished"] > 600:
        return None
    pending = state == "pending"
    return {
        "state": state,
        "userCode": str(flow.get("user_code", "")) if pending else "",
        "uri": str(flow.get("verification_uri", "")) if pending else "",
        "expiresIn": left if pending else 0,
        "error": st.get("error", ""),
    }


# ----------------------------------------------------------------------------------------- one-time codes (TOTP)
def _key(b32: str) -> bytes:
    s = "".join(b32.split()).upper().rstrip("=")
    return base64.b32decode(s + "=" * (-len(s) % 8))


def totp(b32: str, at: float | None = None, digits: int = 6, step: int = 30) -> str:
    """RFC 6238 (HMAC-SHA1, 30 s, 6 digits): the same algorithm as identity\\Persona-Totp.py and every authenticator app."""
    counter = int((time.time() if at is None else at) // step)
    mac = hmac.new(_key(b32), struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off : off + 4])[0] & 0x7FFFFFFF) % (10**digits)
    return f"{code:0{digits}d}"


def _totp_store() -> dict[str, str]:
    try:
        data = json.loads(TOTP_STORE.read_text(encoding="utf-8")) if TOTP_STORE.exists() else {}
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def has_totp(pid: str) -> bool:
    return bool(_totp_store().get(_check(pid)))


def set_totp(pid: str, raw: str) -> None:
    """Store the authenticator 'setup key' for a persona (same store as Persona-Totp.py). Accepts the key or an otpauth:// link."""
    _check(pid)
    text = str(raw or "")
    found = re.search(r"secret=([A-Za-z2-7=]+)", text)
    secret = "".join((found.group(1) if found else text).split()).upper()
    try:
        if len(secret.rstrip("=")) < 10:
            raise ValueError("too short")
        totp(secret)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("That does not look like an authenticator setup key (letters A-Z and digits 2-7, usually 16 or 32 characters).") from exc
    data = _totp_store()
    data[pid] = secret
    _atomic_write(TOTP_STORE, json.dumps(data, indent=2))


def totp_now(pid: str) -> dict[str, Any]:
    secret = _totp_store().get(_check(pid))
    if not secret:
        raise ValueError(f"No setup key stored for {name(pid)} yet - paste it in the box first.")
    return {"code": totp(secret), "secondsLeft": 30 - int(time.time()) % 30}


# ------------------------------------------------------------------------------------- clipboard + private window
_CF_UNICODETEXT = 13
_GMEM_MOVEABLE = 0x0002
# Registered clipboard formats that keep a copy out of Windows clipboard history (Win+V) and the cloud clipboard.
_PRIVATE_FORMATS = (
    ("ExcludeClipboardContentFromMonitorProcessing", b"\x01\x00\x00\x00"),
    ("CanIncludeInClipboardHistory", b"\x00\x00\x00\x00"),
    ("CanUploadToCloudClipboard", b"\x00\x00\x00\x00"),
)
_clip_lock = threading.Lock()
_wipe: threading.Timer | None = None


@functools.lru_cache(maxsize=1)
def _winapi() -> tuple[Any, Any, Any]:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    signatures = (
        (user32.CreateWindowExW, wintypes.HWND, [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                                  ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                                  wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]),
        (user32.DestroyWindow, wintypes.BOOL, [wintypes.HWND]),
        (user32.OpenClipboard, wintypes.BOOL, [wintypes.HWND]),
        (user32.CloseClipboard, wintypes.BOOL, []),
        (user32.EmptyClipboard, wintypes.BOOL, []),
        (user32.GetClipboardData, wintypes.HANDLE, [wintypes.UINT]),
        (user32.SetClipboardData, wintypes.HANDLE, [wintypes.UINT, wintypes.HANDLE]),
        (user32.RegisterClipboardFormatW, wintypes.UINT, [wintypes.LPCWSTR]),
        (kernel32.GlobalAlloc, wintypes.HGLOBAL, [wintypes.UINT, ctypes.c_size_t]),
        (kernel32.GlobalLock, wintypes.LPVOID, [wintypes.HGLOBAL]),
        (kernel32.GlobalUnlock, wintypes.BOOL, [wintypes.HGLOBAL]),
        (kernel32.GlobalFree, wintypes.HGLOBAL, [wintypes.HGLOBAL]),
    )
    for fn, restype, argtypes in signatures:
        fn.restype, fn.argtypes = restype, argtypes
    return ctypes, user32, kernel32


@contextlib.contextmanager
def _clipboard():
    """Open the clipboard under a throwaway owner window (a NULL owner makes SetClipboardData fail); retry while another app holds it."""
    _, user32, _ = _winapi()
    hwnd = user32.CreateWindowExW(0, "STATIC", None, 0, 0, 0, 0, 0, None, None, None, None)
    if not hwnd:
        raise OSError("Could not reach the Windows clipboard.")
    try:
        for _attempt in range(40):
            if user32.OpenClipboard(hwnd):
                break
            time.sleep(0.05)
        else:
            raise OSError("The clipboard is busy - try again.")
        try:
            yield user32
        finally:
            user32.CloseClipboard()
    finally:
        user32.DestroyWindow(hwnd)


def _put(user32: Any, fmt: int, data: bytes) -> None:
    ctypes, _, kernel32 = _winapi()
    handle = kernel32.GlobalAlloc(_GMEM_MOVEABLE, len(data))
    if not handle:
        raise OSError("Out of memory while copying.")
    ptr = kernel32.GlobalLock(handle)
    if not ptr:
        kernel32.GlobalFree(handle)
        raise OSError("Could not copy to the clipboard.")
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(handle)
    if not user32.SetClipboardData(fmt, handle):
        kernel32.GlobalFree(handle)  # on success the clipboard owns the memory
        raise OSError("Could not copy to the clipboard.")


def _clip_set(text: str, private: bool = False) -> None:
    """Replace the clipboard text. `private` also keeps the copy out of clipboard history and the cloud clipboard."""
    with _clip_lock, _clipboard() as user32:
        user32.EmptyClipboard()
        _put(user32, _CF_UNICODETEXT, (text + "\0").encode("utf-16-le"))
        if private:
            for fmt_name, payload in _PRIVATE_FORMATS:
                fmt = user32.RegisterClipboardFormatW(fmt_name)
                if fmt:
                    _put(user32, fmt, payload)


def _clip_get() -> str:
    ctypes, _, kernel32 = _winapi()
    with _clip_lock, _clipboard() as user32:
        handle = user32.GetClipboardData(_CF_UNICODETEXT)
        ptr = kernel32.GlobalLock(handle) if handle else None
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(ptr)
        finally:
            kernel32.GlobalUnlock(handle)


def _clip_clear() -> None:
    with _clip_lock, _clipboard() as user32:
        user32.EmptyClipboard()


def _wipe_later(text: str, seconds: int = 60) -> None:
    """Empty the clipboard after `seconds`, but only if it still holds `text`: the presenter may have copied something else meanwhile.

    Only the latest copy keeps a pending wipe; the clipboard no longer holds the earlier one anyway.
    """
    global _wipe

    def wipe() -> None:
        try:
            if _clip_get() == text:
                _clip_clear()
        except OSError:
            log.warning("Clipboard wipe skipped (clipboard busy).")

    if _wipe is not None:
        _wipe.cancel()
    _wipe = threading.Timer(seconds, wipe)
    _wipe.daemon = True
    _wipe.start()


def _password(pid: str) -> str:
    """The stored password, from `.secrets\\personas.json` ({persona: {upn, password}} - a list of entries is also accepted)."""
    try:
        data = json.loads(PASSWORD_STORE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    if isinstance(data, dict) and isinstance(data.get(pid), dict):
        return str(data[pid].get("password", ""))
    want = upn(pid).lower()
    for entry in data if isinstance(data, list) else []:
        mail = str(entry.get("upn", "")).lower()
        if mail == want or mail.split("@")[0].endswith(pid):
            return str(entry.get("password", ""))
    return ""


def has_password(pid: str) -> bool:
    return bool(_password(_check(pid)))


def clip_password(pid: str, seconds: int = 60) -> dict[str, Any]:
    """Put the persona's password on the clipboard (never returned or printed) and wipe it again after `seconds`."""
    password = _password(_check(pid))
    if not password:
        raise ValueError(f"No stored password for {name(pid)} (.secrets\\personas.json).")
    _clip_set(password, private=True)
    _wipe_later(password, seconds)
    return {"copied": True, "clearsInSeconds": seconds}


_BROWSERS = (
    (r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe", "--inprivate", "Microsoft Edge"),
    (r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe", "--inprivate", "Microsoft Edge"),
    (r"%ProgramFiles%\Google\Chrome\Application\chrome.exe", "--incognito", "Google Chrome"),
    (r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe", "--incognito", "Google Chrome"),
    (r"%LocalAppData%\Google\Chrome\Application\chrome.exe", "--incognito", "Google Chrome"),
)


def browser() -> tuple[Path, str, str] | None:
    for template, flag, nice in _BROWSERS:
        exe = Path(os.path.expandvars(template))
        if exe.is_file():
            return exe, flag, nice
    return None


def open_private_window(pid: str) -> dict[str, Any]:
    """Open the device-login page in a private window with its OWN throwaway profile, and copy the code to the clipboard.

    A separate profile means no cookie is shared with any other window (the presenter's own session, another persona), so
    there is nothing to close between personas.
    """
    _check(pid)
    st = _logins.get(pid)
    if not st or st["state"] != "pending":
        raise ValueError("Press Sign in first - there is no code to enter yet.")
    uri = str(st["flow"].get("verification_uri") or "")
    parsed = urlparse(uri)
    host = parsed.hostname or ""
    if parsed.scheme != "https" or not (host == "microsoft.com" or host.endswith((".microsoft.com", ".microsoftonline.com"))):
        raise ValueError("Unexpected sign-in address - open microsoft.com/devicelogin yourself.")
    found = browser()
    if found is None:
        raise ValueError("Neither Edge nor Chrome was found. Open microsoft.com/devicelogin in a private window yourself.")
    exe, flag, nice = found
    tmp = Path(tempfile.gettempdir())
    for old in tmp.glob("abw-persona-*"):
        if old.is_dir() and time.time() - old.stat().st_mtime > 86400:
            shutil.rmtree(old, ignore_errors=True)
    profile = Path(tempfile.mkdtemp(prefix=f"abw-persona-{pid}-"))
    subprocess.Popen(
        [str(exe), f"--user-data-dir={profile}", flag, "--no-first-run", "--no-default-browser-check", uri],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=DETACHED, close_fds=True,
    )
    _clip_set(str(st["flow"]["user_code"]))
    return {"browser": nice, "codeCopied": True}


# ------------------------------------------------------------------------------------------------------- panel
def state() -> dict[str, Any]:
    """Everything the Personas panel shows. No secrets: only whether a password / setup key / sign-in exists."""
    people = []
    for pid in IDS:
        user = _user(pid)
        people.append({
            "id": pid, "name": name(pid), "job": str(user.get("job") or ""), "label": label(pid), "upn": upn(pid),
            "roles": [{"server": s, "role": r} for s, r in role_pairs(pid)], "groups": list(user.get("groups") or []),
            "story": STORY[pid], "signedIn": signed_in(pid), "hasTotp": has_totp(pid), "hasPassword": has_password(pid),
            "login": login_view(pid),
        })
    found = browser()
    return {
        "operator": {"label": OPERATOR_LABEL, "upn": str(mcpclient.CONFIG.get("operatorUpn", "")), "story": OPERATOR_STORY},
        "personas": people,
        "browser": found[2] if found else "",
    }
