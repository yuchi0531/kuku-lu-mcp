"""MCP server for m.kuku.lu (捨てメアド) — disposable Japanese mailboxes for AI agents."""

__version__ = "0.1.0"

from .client import (  # noqa: F401
    CloudflareBlocked,
    KukuClient,
    KukuError,
    Message,
)
