"""m.kuku.lu (捨てメアド / kuku.lu disposable mail) HTTP client.

Endpoints were reverse-engineered from the site's own JavaScript and cross-checked
against the community wrappers zrpy/kukumail.py and taka-4602/m.kuku.lu-Generator.
No API key is required, but the site sits behind Cloudflare: HTTP requests must
carry browser-like headers and are rate limited per IP.
"""

from __future__ import annotations

import html
import json
import os
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

import httpx

BASE = "https://m.kuku.lu"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,"
    "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
    "accept-language": "ja,en;q=0.9",
    "user-agent": UA,
    "upgrade-insecure-requests": "1",
}

CHALLENGE_MARKERS = (
    "Just a moment",
    "Performing security verification",
    "challenge-platform",
    "cf-challenge",
)


class KukuError(RuntimeError):
    """Any failure talking to m.kuku.lu."""


class CloudflareBlocked(KukuError):
    """Cloudflare returned an interstitial instead of the site."""


def _strip_html(fragment: str) -> str:
    fragment = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", fragment, flags=re.S | re.I)
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"</(p|div|tr|li|h[1-6])>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    text = html.unescape(fragment)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_links(fragment: str) -> list[str]:
    hrefs = re.findall(r'href="([^"]+)"', fragment)
    out = []
    for h in hrefs:
        h = html.unescape(h)
        if h.startswith(("http://", "https://")) and h not in out:
            out.append(h)
    return out


def _email_from(text: str) -> str:
    match = re.search(r"[\w.\-+]+@[\w.\-]+", text or "")
    if match:
        return match.group(0)
    return (text or "").strip().lstrip(":").split(",")[0].strip()


def _extract_codes(text: str) -> list[str]:
    codes = set(re.findall(r"\b\d{4,8}\b", text))
    for m in re.findall(r"\b[A-Z0-9]{4,8}\b", text):
        if any(c.isdigit() for c in m) and any(c.isalpha() for c in m):
            codes.add(m)
    return sorted(codes)


@dataclass
class Message:
    number: str
    key: str
    sender: str
    to: str
    subject: str
    date: str
    unread: bool
    sender_display: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class KukuClient:
    def __init__(
        self,
        state_dir: str | os.PathLike[str] | None = None,
        timeout: float = 25.0,
        proxy: str | None = None,
    ) -> None:
        root = state_dir or os.environ.get("KUKULU_STATE_DIR") or "~/.config/kuku-lu-mcp"
        self.state_path = Path(root).expanduser() / "session.json"
        self.timeout = timeout
        self._lock = threading.RLock()
        self._http = httpx.Client(
            headers=HEADERS, follow_redirects=True, timeout=timeout, proxy=proxy
        )
        self.state: dict[str, Any] = self._load_state()
        if self.state.get("csrf_token"):
            self._restore_cookies()

    # ------------------------------------------------------------------ state
    def _load_state(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_path.read_text("utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), "utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(self.state_path)

    def _restore_cookies(self) -> None:
        self._http.cookies.clear()
        self._set_cookie("cookie_csrf_token", self.state["csrf_token"])
        if self.state.get("session_hash"):
            self._set_cookie("cookie_sessionhash", self.state["session_hash"])

    def _set_cookie(self, name: str, value: str) -> None:
        # m.kuku.lu hands out the same cookie on several paths, which makes
        # httpx raise CookieConflict on .get(); keep one canonical entry.
        jar = self._http.cookies.jar
        for cookie in [c for c in jar if c.name == name]:
            jar.clear(cookie.domain, cookie.path, cookie.name)
        self._http.cookies.set(name, value, domain="m.kuku.lu", path="/")

    def _cookie(self, name: str) -> str | None:
        values = [c.value for c in self._http.cookies.jar if c.name == name and c.value]
        return values[-1] if values else None

    def _dedupe_cookies(self) -> None:
        seen: set[str] = set()
        for cookie in list(self._http.cookies.jar):
            if cookie.name in seen:
                self._http.cookies.jar.clear(cookie.domain, cookie.path, cookie.name)
            else:
                seen.add(cookie.name)

    # ----------------------------------------------------------------- plumbing
    def _check(self, resp: httpx.Response) -> str:
        body = resp.text
        if resp.status_code >= 400:
            raise KukuError(f"HTTP {resp.status_code} from {resp.url}")
        if any(marker in body for marker in CHALLENGE_MARKERS) and "area_numberview" not in body:
            raise CloudflareBlocked(
                "Cloudflare blocked the request (bot check). "
                "Use a browser-like client, a Japanese residential IP, or retry later."
            )
        return body

    def _get(self, path: str, **params: Any) -> str:
        body = self._check(self._http.get(BASE + path, params=params or None))
        self._dedupe_cookies()
        return body

    def _post(self, path: str, data: Any, **kwargs: Any) -> str:
        body = self._check(self._http.post(BASE + path, data=data, **kwargs))
        self._dedupe_cookies()
        return body

    def _token(self) -> str:
        tok = self._cookie("cookie_csrf_token") or self.state.get("csrf_token")
        if not tok:
            raise KukuError("no CSRF token - session is not initialised")
        if tok != self.state.get("csrf_token"):
            self.state["csrf_token"] = tok
            self._save_state()
        return tok

    def _ensure_session(self) -> None:
        """Create (or revive) the kuku.lu account session.

        kuku.lu throttles new sessions per IP, so the credentials are persisted
        and reused: one install == one throwaway account holding all addresses.
        """
        with self._lock:
            if not self.state.get("csrf_token"):
                self._bootstrap()
                return
            body = self._get("/index.php")
            if "area_numberview" not in body:
                self._bootstrap()
                return
            tok = self._cookie("cookie_csrf_token")
            if tok and tok != self.state.get("csrf_token"):
                self.state["csrf_token"] = tok
                self._save_state()
            m = re.search(r'id="area_numberview"[^>]*>([^<]+)<', body)
            if m and m.group(1).strip() != self.state.get("account_id"):
                self.state["account_id"] = m.group(1).strip()
                self._save_state()

    def _bootstrap(self) -> None:
        body = self._get("/index.php")
        tok = self._cookie("cookie_csrf_token")
        sess = self._cookie("cookie_sessionhash")
        if not tok:
            raise CloudflareBlocked(
                "m.kuku.lu did not hand out a session cookie (likely blocked)."
            )
        acc = re.search(r'id="area_numberview"[^>]*>([^<]+)<', body)
        pwd = re.search(r'id="area_passwordview_copy"[^>]*>([^<]+)<', body)
        ip = re.search(r"checkNewMailUser&ip=(\d+\.\d+\.\d+\.\d+)", body)
        self.state = {
            "csrf_token": tok,
            "session_hash": sess,
            "account_id": acc.group(1).strip() if acc else None,
            "password": pwd.group(1).strip() if pwd else None,
            "client_ip": ip.group(1) if ip else None,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self._save_state()
        self._get(
            "/index.php",
            action="agreeEULA",
            nopost=1,
            by_system=1,
            csrf_token_check=tok,
        )

    # ------------------------------------------------------------------- tools
    def account(self) -> dict[str, Any]:
        self._ensure_session()
        return {
            "account_id": self.state.get("account_id"),
            "password": self.state.get("password"),
            "session_hash": self.state.get("session_hash"),
            "state_file": str(self.state_path),
            "note": "Keep these to reopen the same mailbox set from m.kuku.lu in a browser.",
        }

    def domains(self) -> list[str]:
        self._ensure_session()
        body = self._get("/index.php")
        doms = re.findall(r'name="input_manualmaildomain"[^>]*value="([^"]+)"', body)
        return sorted(set(doms))

    def create_address(
        self,
        kind: str = "auto",
        username: str | None = None,
        domain: str | None = None,
    ) -> dict[str, Any]:
        """kind: auto (random), onetime (expires), custom (pick user/domain)."""
        self._ensure_session()
        tok = self._token()
        stamp = int(time.time() * 1000)

        if kind == "auto":
            txt = self._get(
                "/index.php",
                action="addMailAddrByAuto",
                nopost=1,
                by_system=1,
                csrf_token_check=tok,
                recaptcha_token="",
                _=stamp,
            )
            if not txt.startswith("OK:"):
                raise KukuError(f"address creation failed: {txt[:200]}")
            return {"address": _email_from(txt), "kind": "auto", "expires": None}

        if kind == "onetime":
            txt = self._get(
                "/index.php",
                action="addMailAddrByOnetime",
                nopost=1,
                by_system=1,
                csrf_token_check=tok,
                recaptcha_token="",
                _=stamp,
            )
            if not txt.startswith("OK:"):
                raise KukuError(f"address creation failed: {txt[:200]}")
            parts = txt[2:].split(",,")
            return {
                "address": _email_from(parts[0]),
                "kind": "onetime",
                "expires": parts[1].strip() if len(parts) > 1 else None,
            }

        if kind == "custom":
            if not username or not domain:
                raise KukuError("kind='custom' needs both username and domain")
            ip = self.state.get("client_ip") or ""
            chk = self._get(
                "/index.php",
                action="checkNewMailUser",
                ip=ip,
                nopost=1,
                csrf_token_check=tok,
                newdomain=domain,
                newuser=username,
            )
            if chk.strip() != "OK":
                raise KukuError(f"name check failed: {chk.strip()[:200]}")
            txt = self._get(
                "/index.php",
                action="addMailAddrByManual",
                nopost=1,
                by_system=1,
                t=int(time.time()),
                csrf_token_check=tok,
                newdomain=domain,
                newuser=username,
                recaptcha_token="",
            )
            if not txt.startswith("OK:"):
                raise KukuError(f"address creation failed: {txt[:200]}")
            return {"address": _email_from(txt), "kind": "custom", "expires": None}

        raise KukuError("kind must be one of: auto, onetime, custom")

    def list_addresses(self) -> list[str]:
        self._ensure_session()
        body = self._get("/index._addrlist.php", nopost=1, _=int(time.time() * 1000))
        return sorted(set(re.findall(r'openMailAddrData\("([^"]+)"\)', body)))

    def delete_address(self, address: str, delete_mail: bool = False) -> dict[str, Any]:
        """Remove an address. delete_mail=True also discards its received mail."""
        self._ensure_session()
        tok = self._token()
        txt = self._post(
            "/index.php",
            {
                "action": "delMailAddr",
                "nopost": 1,
                "csrf_token_check": tok,
                "addr": address,
                "type": "" if delete_mail else "1",
            },
        )
        ok = txt.strip().startswith("OK")
        left = None
        if ok and ":" in txt[:12]:
            tail = txt.strip().split(":", 1)[1]
            left = int(tail) if tail.isdigit() else None
        return {"address": address, "deleted": ok, "remaining": left}

    def list_messages(self, address: str) -> list[Message]:
        self._ensure_session()
        tok = self._token()
        body = self._get(
            "/recv._ajax.php",
            nopost=1,
            csrf_token_check=tok,
            q=address,
            _=int(time.time() * 1000),
        )
        msgs: list[Message] = []
        for m in re.finditer(
            r"openMailData\('(\d+)',\s*'(\w+)',\s*'([^']+)'", body
        ):
            num, key, raw = m.group(1), m.group(2), html.unescape(m.group(3))
            fields = dict(
                part.split("=", 1) for part in raw.split(";") if "=" in part
            )
            sender = urllib.parse.unquote(fields.get("from", ""))
            to = urllib.parse.unquote(fields.get("to", ""))
            block = self._mail_block(body, num)
            subject = ""
            tmatch = re.search(
                rf'id="area_mail_title_{num}".*?'
                r'<span style="overflow-wrap: break-word;word-break: break-all;">'
                r"(.+?)</span>",
                block,
                re.S,
            )
            if tmatch:
                subject = _strip_html(tmatch.group(1))
            dmatch = re.search(r"(\d+/\d+, \d+時\d+分)", block)
            date = dmatch.group(1).strip() if dmatch else ""
            smatch = re.search(r"\| (.*?)&raquo;", block, re.S)
            sender_display = _strip_html(smatch.group(1)) if smatch else ""
            msgs.append(
                Message(
                    number=num,
                    key=key,
                    sender=sender,
                    sender_display=sender_display,
                    to=to,
                    subject=subject,
                    date=date,
                    unread=f'tableUnreadNum["{num}"] = true' in block,
                )
            )
        return msgs

    @staticmethod
    def _mail_block(body: str, num: str) -> str:
        start = body.find(f'id="area_mail_{num}"')
        if start < 0:
            start = max(0, body.find(f'id="area_maildata_{num}"') - 3000)
        nxt = body.find('id="area_maildata_', start + 10)
        return body[start : nxt if nxt > 0 else start + 8000]

    def read_message(self, address: str, number: str, key: str | None = None) -> dict[str, Any]:
        self._ensure_session()
        if key is None:
            for msg in self.list_messages(address):
                if msg.number == number:
                    key, subject, sender = msg.key, msg.subject, msg.sender
                    break
            else:
                raise KukuError(f"message {number} not found in {address}")
        else:
            meta = next(
                (m for m in self.list_messages(address) if m.number == number),
                None,
            )
            subject = meta.subject if meta else ""
            sender = meta.sender if meta else ""
        body = self._post(
            "/smphone.app.recv.view.php",
            "",
            params={"num": number, "key": key, "noscroll": 1},
        )
        inner = body
        dmatch = re.search(r'<div id="area-data"[^>]*>(.*)</div>', body, re.S)
        if dmatch:
            inner = dmatch.group(1)
        text = _strip_html(inner)
        return {
            "number": number,
            "subject": subject,
            "from": sender,
            "text": text,
            "codes": _extract_codes(text),
            "links": _extract_links(inner),
        }

    def wait_for_message(
        self,
        address: str,
        timeout: float = 90.0,
        from_contains: str | None = None,
        subject_contains: str | None = None,
        since_number: str | None = None,
        interval: float = 3.0,
        read: bool = False,
    ) -> dict[str, Any]:
        """Poll until a matching mail lands, then (optionally) return its body."""
        deadline = time.time() + max(5.0, timeout)
        seen = set()
        while True:
            for msg in self.list_messages(address):
                if since_number and msg.number.isdigit() and int(msg.number) < int(since_number):
                    continue
                if from_contains and from_contains.lower() not in msg.sender.lower():
                    continue
                if subject_contains and subject_contains.lower() not in msg.subject.lower():
                    continue
                if msg.number in seen:
                    continue
                seen.add(msg.number)
                result = msg.as_dict()
                if read:
                    result.update(self.read_message(address, msg.number, msg.key))
                return result
            if time.time() >= deadline:
                raise KukuError(
                    f"no matching mail in {address} within {int(timeout)}s "
                    f"(filters: from={from_contains!r}, subject={subject_contains!r})"
                )
            time.sleep(interval)

    def latest_number(self, address: str) -> str | None:
        msgs = self.list_messages(address)
        nums = [m.number for m in msgs if m.number.isdigit()]
        return max(nums, key=int) if nums else None

    def close(self) -> None:
        self._http.close()
