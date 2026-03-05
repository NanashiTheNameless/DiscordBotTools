#!/usr/bin/env python3.14
# This software is licensed under NNCL v1.3 see LICENSE.md for more info
# https://github.com/NanashiTheNameless/DiscordBotTools/blob/main/LICENSE.md

import argparse
import asyncio
import getpass
import sys

import discord  # pyright: ignore[reportMissingImports]
from discord.errors import (  # pyright: ignore[reportMissingImports]
    Forbidden,
    HTTPException,
    NotFound,
)


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Get owner information for a Discord guild (server)."
    )
    p.add_argument("--token", help="Bot token. If omitted, prompts.")
    p.add_argument(
        "--guild-id", type=int, help="Target guild (server) ID (prompts if omitted)."
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

    guild_id = args.guild_id
    while guild_id is None:
        try:
            raw = input("Target guild ID: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("Error: No guild ID provided.", file=sys.stderr)
            return 2
        if not raw:
            continue
        try:
            guild_id = int(raw)
        except ValueError:
            print("Invalid guild ID, please enter digits only.", file=sys.stderr)
            continue

    intents = discord.Intents.none()
    intents.guilds = True

    client = discord.Client(intents=intents)
    done = asyncio.get_running_loop().create_future()
    result = {
        "guild_name": None,
        "guild_id": guild_id,
        "owner_id": None,
        "owner_user": None,
    }

    @client.event
    async def on_ready():
        try:
            guild = client.get_guild(guild_id)
            if guild is None:
                try:
                    guild = await client.fetch_guild(guild_id)
                except NotFound:
                    print(f"Error: Guild {guild_id} not found.", file=sys.stderr)
                    done.set_result(False)
                    return
                except Forbidden:
                    print(
                        "Error: Bot cannot access that guild.",
                        file=sys.stderr,
                    )
                    done.set_result(False)
                    return
                except HTTPException as exc:
                    print(
                        f"Error: HTTP error while fetching guild: {exc}",
                        file=sys.stderr,
                    )
                    done.set_result(False)
                    return

            owner_id = getattr(guild, "owner_id", None)
            owner_user = None
            if owner_id is not None:
                try:
                    owner_user = await client.fetch_user(owner_id)
                except (NotFound, HTTPException):
                    owner_user = None

            result["guild_name"] = guild.name
            result["owner_id"] = owner_id
            result["owner_user"] = owner_user
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

    if not done.result():
        return 1

    print(f"Guild: {result['guild_name']} ({result['guild_id']})")
    if result["owner_id"] is None:
        print("Owner ID: unavailable")
    else:
        print(f"Owner ID: {result['owner_id']}")
        if result["owner_user"] is not None:
            print(
                f"Owner Username: {result['owner_user']} ({result['owner_user'].id})"
            )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
