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
)


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Leave a Discord guild (server).")
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

    client = discord.Client(intents=intents)
    done = asyncio.get_running_loop().create_future()

    @client.event
    async def on_ready():
        try:
            try:
                guild = client.get_guild(guild_id)
                if guild is None:
                    print(f"Error: Guild {guild_id} not found.", file=sys.stderr)
                    done.set_result(False)
                    return
            except Exception as exc:
                print(f"Error: Could not fetch guild: {exc}", file=sys.stderr)
                done.set_result(False)
                return

            print(f"Logged in as {client.user} (id: {client.user.id})")
            print(f"Leaving guild: {guild.name} (id: {guild.id})")

            try:
                await guild.leave()
                print(f"Successfully left {guild.name}.")
                done.set_result(True)
            except Forbidden:
                print(
                    "Error: Forbidden to leave guild (this should not happen).",
                    file=sys.stderr,
                )
                done.set_result(False)
            except HTTPException as exc:
                print(f"Error: HTTP error while leaving guild: {exc}", file=sys.stderr)
                done.set_result(False)
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

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
