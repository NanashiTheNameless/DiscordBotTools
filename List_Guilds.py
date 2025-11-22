#!/usr/bin/env python3
# This software is licensed under NNCL v1.2 see LICENSE.md for more info
# https://github.com/NanashiTheNameless/DiscordBotTools/blob/main/LICENSE.md

import sys
import json
import argparse
import asyncio
import getpass
from typing import Any
import discord # pyright: ignore[reportMissingImports]

def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="List all Discord guilds (servers) a bot is in."
    )
    p.add_argument(
        "--token",
        help="Bot token. If omitted, prompts."
    )
    p.add_argument(
        "--format",
        choices=["text", "json", "csv"],
        default="text",
        help="Output format."
    )
    p.add_argument(
        "--include-counts",
        action="store_true",
        help="Include member_count (may be approximate without Members intent)."
    )
    p.add_argument(
        "--include-owner",
        action="store_true",
        help="Include owner_id (no additional permissions required)."
    )
    return p

async def main() -> int:
    args = build_argparser().parse_args()
    token = args.token
    if not token:
        try:
            token = getpass.getpass("Bot token: ")
        except (EOFError, KeyboardInterrupt):
            print("Error: No bot token provided.", file=sys.stderr)
            return 2
    if not token:
        print("Error: No bot token provided.", file=sys.stderr)
        return 2

    intents = discord.Intents.none()
    intents.guilds = True

    client = discord.Client(intents=intents)

    done = asyncio.get_running_loop().create_future()
    data: dict[str, list[dict[str, Any]]] = {"guilds": []}

    @client.event
    async def on_ready():
        try:
            for g in client.guilds:
                item = {
                    "id": g.id,
                    "name": g.name,
                }
                if args.include_owner:
                    item["owner_id"] = getattr(g, "owner_id", None)
                if args.include_counts:
                    item["member_count"] = getattr(g, "member_count", None)
                data["guilds"].append(item)

            data["guilds"].sort(key=lambda x: (x["name"] or "").lower())
            done.set_result(True)
        except Exception as exc:
            done.set_exception(exc)

    async def run():
        try:
            await client.start(token)
        except discord.LoginFailure:
            print("Error: Invalid bot token.", file=sys.stderr)
            return 3
        return 0

    task = asyncio.create_task(run())
    await asyncio.wait({done}, return_when=asyncio.ALL_COMPLETED)
    await client.close()
    try:
        await task
    except Exception:
        pass

    fmt = args.format
    guilds = data["guilds"]

    if fmt == "json":
        json.dump(guilds, sys.stdout, indent=2)
        print()
    elif fmt == "csv":
        headers = ["id", "name"]
        if args.include_owner:
            headers.append("owner_id")
        if args.include_counts:
            headers.append("member_count")
        print(",".join(headers))
        for g in guilds:
            row = [str(g.get("id", "")), (g.get("name", "") or "").replace(",", " ")]
            if args.include_owner:
                row.append(str(g.get("owner_id", "")))
            if args.include_counts:
                row.append(str(g.get("member_count", "")))
            print(",".join(row))
    else:
        if not guilds:
            print("No guilds found.")
        else:
            for g in guilds:
                parts = [f'{g["name"]} (id={g["id"]})']
                if args.include_owner and g.get("owner_id") is not None:
                    parts.append(f'owner_id={g["owner_id"]}')
                if args.include_counts and g.get("member_count") is not None:
                    parts.append(f'member_count={g["member_count"]}')
                print(" • " + "  ".join(parts))

    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
