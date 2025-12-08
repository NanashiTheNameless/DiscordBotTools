#!/usr/bin/env python3
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
        description="Delete this bot's messages in the DM channel with a specific user."
    )
    p.add_argument("--token", help="Bot token. If omitted, prompts.")
    p.add_argument("--user-id", type=int, help="Target user ID (prompts if omitted).")
    p.add_argument(
        "--sleep",
        type=float,
        default=0.3,
        help="Delay (seconds) between deletions to avoid rate limits. Default: 0.3",
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

    user_id = args.user_id
    while user_id is None:
        try:
            raw = input("Target user ID: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("Error: No user ID provided.", file=sys.stderr)
            return 2
        if not raw:
            continue
        try:
            user_id = int(raw)
        except ValueError:
            print("Invalid user ID, please enter digits only.", file=sys.stderr)
            continue

    intents = discord.Intents.none()
    intents.messages = True
    intents.dm_messages = True

    client = discord.Client(intents=intents)
    done = asyncio.get_running_loop().create_future()
    stats = {"deleted": 0, "failed": 0}

    @client.event
    async def on_ready():
        print(f"Logged in as {client.user} (id: {client.user.id})")
        try:
            try:
                user = await client.fetch_user(user_id)
            except NotFound:
                print("Error: Target user not found.", file=sys.stderr)
                done.set_result(False)
                return
            except HTTPException as exc:
                print(f"Error: HTTP error while fetching user: {exc}", file=sys.stderr)
                done.set_result(False)
                return

            try:
                dm_channel = await user.create_dm()
            except HTTPException as exc:
                print(
                    f"Error: Could not create or fetch DM channel: {exc}",
                    file=sys.stderr,
                )
                done.set_result(False)
                return

            if not isinstance(dm_channel, discord.DMChannel):
                print("Error: Unexpected channel type, aborting.", file=sys.stderr)
                done.set_result(False)
                return

            print(f"DM channel with {user} is {dm_channel.id}. Fetching messages...")

            async for message in dm_channel.history(limit=None, oldest_first=True):
                if message.author.id != client.user.id:
                    continue

                try:
                    await message.delete()
                    stats["deleted"] += 1
                    if args.sleep > 0:
                        await asyncio.sleep(args.sleep)  # be gentle with rate limits
                except Forbidden:
                    stats["failed"] += 1
                    print(
                        f"Forbidden: could not delete message {message.id}",
                        file=sys.stderr,
                    )
                except HTTPException as exc:
                    stats["failed"] += 1
                    print(
                        f"HTTP error deleting message {message.id}: {exc}",
                        file=sys.stderr,
                    )

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

    print(
        f"Done. Deleted {stats['deleted']} messages. Failed to delete {stats['failed']} messages."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
