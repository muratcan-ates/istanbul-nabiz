#!/usr/bin/env python3
"""Prepare the daily follow digest for every example account (DECISIONS #36).

For each account with followed topics, at most once per Istanbul day: evaluate the topics through
the one facade (alert engine, station list, service-page index), keep only the essential changes
(a new or cleared fault, a line notice, a new service page) and hand one e-mail to the sender.

The sender is the outbox (``data/outbox/``, nothing leaves the machine) unless ``--deliver`` is
given *and* ``NABIZ_ACS_CONNECTION_STRING`` and ``NABIZ_ACS_SENDER`` are set. The example sign-in
verifies no address, so ``--deliver`` stays the owner's decision until real sign-in exists.

``make notify-digest`` runs it offline, from the recorded fixtures. Without ``NABIZ_OFFLINE=1`` the
facade reads İBB through the shared polite client and cache, once per distinct topic.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from ibb_mcp.sources.base import SourceContext  # noqa: E402
from ibb_mcp.tools import Nabiz  # noqa: E402
from nabiz.console.accounts import AccountStore  # noqa: E402
from nabiz.console.digest import run_digest  # noqa: E402
from nabiz.console.email_sender import AcsEmailSender, OutboxEmailSender, outbox_dir_from_env, sender_from_env  # noqa: E402


async def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--deliver", action="store_true", help="send through ACS when it is configured (owner only)")
    args = parser.parse_args(argv)
    if args.deliver and AcsEmailSender.from_env() is None:
        print("ACS ayarlı değil (NABIZ_ACS_CONNECTION_STRING, NABIZ_ACS_SENDER boş); gönderim yapılmadı.", file=sys.stderr)
        return 2
    store = AccountStore.from_env()
    outbox = OutboxEmailSender(outbox_dir_from_env())
    sender = sender_from_env(deliver=args.deliver)
    nabiz = Nabiz(SourceContext.create())
    try:
        report = await run_digest(store, nabiz, sender, outbox=outbox)
    finally:
        await nabiz.aclose()
        store.close()
    summary = {**report.as_dict(), "sender": sender.name, "outbox": str(outbox.directory) if sender.name == "outbox" else None}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
