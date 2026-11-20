"""End-to-end check against the real m.kuku.lu service (network required).

1. creates an address, 2. triggers a real inbound mail via formsubmit.co,
3. waits for it, 4. prints subject / codes / links.

Run:  PYTHONPATH= python -m tests.e2e      (or: python tests/e2e.py)
"""

from __future__ import annotations

import json
import sys
import time

import httpx

from kukulumcp import KukuClient


def trigger_mail(target: str) -> None:
    """formsubmit.co sends an activation mail to any address, no account needed."""
    httpx.post(
        f"https://formsubmit.co/ajax/{target}",
        json={"name": "kuku-lu-mcp e2e", "message": "delivery probe OTP 445566", "_subject": f"e2e {int(time.time())}"},
        headers={
            "user-agent": "Mozilla/5.0",
            "referer": "https://formsubmit.co/",
            "origin": "https://formsubmit.co",
            "accept": "application/json",
        },
        timeout=25,
    )


def main() -> int:
    client = KukuClient()
    print("account:", client.account()["account_id"])
    addr = client.create_address("auto")["address"]
    print("created:", addr)
    trigger_mail(addr)
    msg = client.wait_for_message(addr, timeout=120)
    print("received:", json.dumps(msg, ensure_ascii=False))
    full = client.read_message(addr, msg["number"], msg["key"])
    print("subject:", full["subject"])
    print("from:", full["from"])
    print("codes:", full["codes"])
    print("links:", full["links"][:3])
    print("text head:", full["text"][:160].replace("\n", " "))
    print("OK" if msg["subject"] else "FAIL: empty subject")
    client.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
