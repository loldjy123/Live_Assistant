"""Start the local server once and open its browser page. No login service needed."""

import argparse
import fcntl
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_ID = "live-book-inventory"
PROJECT_ID = hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]
APP_URL = "http://localhost:8080/"
HEALTH_URL = "http://127.0.0.1:8080/health"
LOG_PATH = ROOT / ".server.log"


def read_health():
    # A local request should never go through a configured internet proxy.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(HEALTH_URL, timeout=2) as response:
            health = json.load(response)
    except (OSError, ValueError):
        return None
    if not isinstance(health, dict):
        return None
    if health.get("app") != APP_ID or health.get("project") != PROJECT_ID:
        return None
    return health


def start_server():
    """Serialize double-clicks, reuse this project's server, and verify readiness."""
    with (ROOT / ".server.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        health = read_health()
        if health and health.get("ready"):
            if health.get("websocket_path") != "/ws":
                raise RuntimeError(
                    "An older server is running. Open Stop Library.command, "
                    "then Open Library.command to load the current app."
                )
            return False

        python = ROOT / ".venv" / "bin" / "python"
        if not python.is_file():
            raise RuntimeError("Missing .venv. Follow the setup steps in README.md first.")

        with LOG_PATH.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(
                [str(python), "-u", str(ROOT / "main.py")],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    "Server could not start. Check .server.log. If an older server is "
                    "running in PyCharm, stop it and open this launcher again."
                )
            health = read_health()
            if health and health.get("ready") and health.get("pid") == process.pid:
                return True
            time.sleep(0.1)

        # This process belongs to this launch attempt; never kill a port owner.
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        raise RuntimeError("Server startup timed out. Check .server.log.")


def stop_server():
    with (ROOT / ".server.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        health = read_health()
        if not health:
            return False
        pid = health.get("pid")
        if type(pid) is not int or pid <= 1 or pid == os.getpid():
            raise RuntimeError("Server returned an invalid process ID; refusing to stop it.")
        try:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            return False
        return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-browser", action="store_true", help="Start without opening a browser")
    parser.add_argument("--stop", action="store_true", help="Stop this project's local server")
    args = parser.parse_args()

    if args.stop:
        print("Server stopping." if stop_server() else "No server from this project is running.")
        return

    started = start_server()
    print("Server started." if started else "Using the running server.")
    print(APP_URL)
    if not args.no_browser:
        webbrowser.open(APP_URL)


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError) as exc:
        print(f"Could not open the app: {exc}", file=sys.stderr)
        raise SystemExit(1)
