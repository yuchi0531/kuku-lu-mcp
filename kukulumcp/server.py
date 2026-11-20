"""Stdio MCP server exposing m.kuku.lu throwaway mailboxes to AI agents."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

from .client import CloudflareBlocked, KukuClient, KukuError

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

mcp = FastMCP(
    "kuku-lu-mcp",
    instructions=(
        "Japanese disposable mailboxes from m.kuku.lu (捨てメアド). "
        "Typical flow: kuku_create_address -> use the address in a signup form -> "
        "kuku_wait_for_message (returns subject/from/codes/links) -> kuku_read_message "
        "if you need the full body. One persisted throwaway account holds all "
        "addresses; do not create a new account per call."
    ),
)

_client: KukuClient | None = None


def client() -> KukuClient:
    global _client
    if _client is None:
        _client = KukuClient(state_dir=os.environ.get("KUKULU_STATE_DIR") or None)
    return _client


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _fail(exc: Exception) -> str:
    if isinstance(exc, CloudflareBlocked):
        return f"ERROR: blocked by Cloudflare - {exc}"
    if isinstance(exc, KukuError):
        return f"ERROR: {exc}"
    return f"ERROR: unexpected {type(exc).__name__}: {exc}"


@mcp.tool()
def kuku_account() -> str:
    """Show the persisted throwaway account (ID / password / state file).

    These credentials reopen the same set of addresses from m.kuku.lu in a
    browser, which is useful when a site needs the mailbox to be checked by hand.
    """
    try:
        return _json(client().account())
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool()
def kuku_create_address(
    kind: str = "auto",
    username: str | None = None,
    domain: str | None = None,
) -> str:
    """Create a new throwaway address on m.kuku.lu.

    Args:
        kind: "auto" random address, "onetime" address that expires on its own,
            or "custom" to pick the local part yourself (needs username+domain,
            see kuku_list_domains).
        username: local part for kind="custom".
        domain: domain for kind="custom".

    Returns JSON with the address (and the expiry date for one-time addresses).
    """
    try:
        return _json(client().create_address(kind=kind, username=username, domain=domain))
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool()
def kuku_list_addresses() -> str:
    """List every address currently held by this account."""
    try:
        return _json(client().list_addresses())
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool()
def kuku_list_domains() -> str:
    """List the domains available for kind="custom" address creation."""
    try:
        return _json(client().domains())
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool()
def kuku_delete_address(address: str, delete_mail: bool = False) -> str:
    """Delete an address from the account.

    Args:
        address: address to remove.
        delete_mail: also discard mail already received by that address
            (default false keeps the messages on the server).
    """
    try:
        return _json(client().delete_address(address, delete_mail=delete_mail))
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool()
def kuku_list_messages(address: str, limit: int = 20) -> str:
    """List the mails in one address's inbox (newest first, metadata only)."""
    try:
        msgs = [m.as_dict() for m in client().list_messages(address)]
        msgs.sort(key=lambda m: int(m["number"]) if m["number"].isdigit() else 0, reverse=True)
        return _json(msgs[: max(1, limit)])
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool()
def kuku_read_message(address: str, number: str) -> str:
    """Read one mail in full: text body, extracted verification codes and links."""
    try:
        return _json(client().read_message(address, number))
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


@mcp.tool()
def kuku_wait_for_message(
    address: str,
    timeout_seconds: int = 90,
    from_contains: str | None = None,
    subject_contains: str | None = None,
    read: bool = True,
) -> str:
    """Block until a mail arrives, then return it (body, codes and links included).

    Use this right after submitting a signup form so the inbox is not polled by
    the model itself. Filters narrow the wait to the mail you expect.

    Args:
        address: address created by kuku_create_address.
        timeout_seconds: how long to wait before giving up (max 600).
        from_contains: case-insensitive substring match on the sender address.
        subject_contains: case-insensitive substring match on the subject.
        read: also fetch the full body/codes/links (default true).
    """
    try:
        timeout = min(600, max(5, timeout_seconds))
        msg = client().wait_for_message(
            address,
            timeout=timeout,
            from_contains=from_contains,
            subject_contains=subject_contains,
            read=read,
        )
        return _json(msg)
    except Exception as exc:  # noqa: BLE001
        return _fail(exc)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
