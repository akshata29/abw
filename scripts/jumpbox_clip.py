"""Copy the jump-box admin password to the clipboard, then clear it again.

Used by scripts\\jumpbox.ps1 -CopyPassword. The password is read from .secrets\\jumpbox.json and is never printed.

    jumpbox_clip.py copy [seconds]    copy it (kept out of Win+V history and the cloud clipboard) and start the wipe
    jumpbox_clip.py wipe <seconds>    internal: wait, then clear the clipboard only if it still holds the password

The wipe runs as a detached process, so closing the window that launched it cannot leave the password on the clipboard.
The clipboard helpers are the ones the console's persona switcher uses.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True  # must be set before the console modules are imported

ROOT = Path(__file__).resolve().parents[1]
SECRET_FILE = ROOT / ".secrets" / "jumpbox.json"
DEFAULT_SECONDS = 120

sys.path.insert(0, str(ROOT / "console"))
sys.path.insert(0, str(ROOT / "demo"))
import personas  # noqa: E402  (needs the paths above; also loads the demo's mcpclient)


def read_password() -> str:
    try:
        data = json.loads(SECRET_FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return ""
    return str(data.get("password", "")) if isinstance(data, dict) else ""


def wipe(seconds: int) -> int:
    password = read_password()
    time.sleep(seconds)
    try:
        if password and personas._clip_get() == password:
            personas._clip_clear()
    except OSError:
        return 1  # clipboard busy: nothing more a detached process can do
    return 0


def copy(seconds: int) -> int:
    password = read_password()
    if not password:
        print("No jump-box password found (.secrets\\jumpbox.json). Deploy first: pwsh scripts\\jumpbox.ps1")
        return 2
    try:
        personas._clip_set(password, private=True)
    except OSError as exc:
        print(f"Could not copy to the clipboard: {exc}")
        return 1
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "wipe", str(seconds)],
        creationflags=flags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    print(f"Password copied (kept out of clipboard history). It clears from the clipboard in {seconds} s.")
    return 0


def main(argv: list[str]) -> int:
    action = argv[1] if len(argv) > 1 else "copy"
    seconds = int(argv[2]) if len(argv) > 2 and argv[2].isdigit() else DEFAULT_SECONDS
    if action == "copy":
        return copy(seconds)
    if action == "wipe":
        return wipe(seconds)
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
