"""Tiny CLI used for manual testing / debugging: python -m kukulumcp.cli <cmd>"""

from __future__ import annotations

import argparse
import json
import sys

from .client import KukuClient, KukuError


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kukulumcp")
    p.add_argument("--state-dir", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("account")
    sub.add_parser("domains")
    c = sub.add_parser("create")
    c.add_argument("kind", nargs="?", default="auto", choices=["auto", "onetime", "custom"])
    c.add_argument("--user")
    c.add_argument("--domain")
    sub.add_parser("ls")
    m = sub.add_parser("msgs")
    m.add_argument("address")
    r = sub.add_parser("read")
    r.add_argument("address")
    r.add_argument("number")
    w = sub.add_parser("wait")
    w.add_argument("address")
    w.add_argument("--timeout", type=float, default=90)
    w.add_argument("--from-contains", default=None)
    w.add_argument("--subject-contains", default=None)
    d = sub.add_parser("del")
    d.add_argument("address")
    d.add_argument("--with-mail", action="store_true")

    args = p.parse_args(argv)
    client = KukuClient(state_dir=args.state_dir)
    try:
        if args.cmd == "account":
            out = client.account()
        elif args.cmd == "domains":
            out = client.domains()
        elif args.cmd == "create":
            out = client.create_address(args.kind, args.user, args.domain)
        elif args.cmd == "ls":
            out = client.list_addresses()
        elif args.cmd == "msgs":
            out = [m.as_dict() for m in client.list_messages(args.address)]
        elif args.cmd == "read":
            out = client.read_message(args.address, args.number)
        elif args.cmd == "wait":
            out = client.wait_for_message(
                args.address,
                timeout=args.timeout,
                from_contains=args.from_contains,
                subject_contains=args.subject_contains,
                read=True,
            )
        elif args.cmd == "del":
            out = client.delete_address(args.address, delete_mail=args.with_mail)
        else:  # pragma: no cover
            p.error("unknown command")
    except KukuError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
