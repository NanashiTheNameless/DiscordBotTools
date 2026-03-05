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

try:
    import readline
except ImportError:
    readline = None


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Interactive DM terminal as your bot (send, edit, delete)."
    )
    p.add_argument("--token", help="Bot token. If omitted, prompts.")
    p.add_argument("--user-id", type=int, help="Target user ID (prompts if omitted).")
    p.add_argument(
        "--history",
        type=int,
        default=10,
        help="Show this many recent messages on connect and for /list default. Default: 10",
    )
    return p


def prompt_for_user_id(initial_value: int | None) -> int | None:
    user_id = initial_value
    while user_id is None:
        try:
            raw = input("Target user ID: ").strip()
        except EOFError:
            return None
        if not raw:
            continue
        try:
            user_id = int(raw)
        except ValueError:
            print("Invalid user ID, please enter digits only.", file=sys.stderr)
    return user_id


def normalize_content(content: str) -> str:
    text = content.replace("\n", "\\n")
    if len(text) > 180:
        return text[:177] + "..."
    return text


def format_message_line(message: discord.Message, bot_user_id: int) -> str:
    author = "bot" if message.author.id == bot_user_id else str(message.author)
    content = normalize_content(message.content or "")
    if not content and message.attachments:
        content = f"[{len(message.attachments)} attachment(s)]"
    if not content:
        content = "[empty]"
    return f"{message.id}  {author}: {content}"


def print_help() -> None:
    print("Commands:")
    print("  /help                      Show this help")
    print("  /list [count]              Show recent DM messages")
    print("  /send <text>               Send a message")
    print("  /edit <message_id> <text>  Edit one of the bot's messages")
    print("  /delete <message_id>       Delete one of the bot's messages")
    print("  /edit-last <text>          Edit the last bot message")
    print("  /delete-last               Delete the last bot message")
    print("  /quit                      Exit")
    print("Tip: entering plain text (without a leading /) sends that text.")


def configure_line_editing() -> None:
    if readline is None:
        return
    try:
        readline.parse_and_bind("set editing-mode emacs")
        readline.parse_and_bind('"\\e[D": backward-char')
        readline.parse_and_bind('"\\e[C": forward-char')
    except Exception:
        return


async def show_history(
    dm_channel: discord.DMChannel, bot_user_id: int, limit: int
) -> None:
    count = max(1, min(limit, 100))
    try:
        # Fetch latest messages, then print oldest->newest within that window.
        messages = [message async for message in dm_channel.history(limit=count)]
        messages.reverse()
    except HTTPException as exc:
        print(f"Error: HTTP error while reading history: {exc}", file=sys.stderr)
        return

    if not messages:
        print("(No messages in history)")
        return

    for message in messages:
        print(format_message_line(message, bot_user_id))


async def find_last_bot_message_id(
    dm_channel: discord.DMChannel, bot_user_id: int
) -> int | None:
    try:
        async for message in dm_channel.history(limit=100):
            if message.author.id == bot_user_id:
                return message.id
    except HTTPException:
        return None
    return None


async def fetch_owned_message(
    dm_channel: discord.DMChannel, message_id: int, bot_user_id: int
) -> discord.Message | None:
    try:
        message = await dm_channel.fetch_message(message_id)
    except NotFound:
        print(f"Error: Message {message_id} not found.", file=sys.stderr)
        return None
    except HTTPException as exc:
        print(f"Error: HTTP error while fetching message: {exc}", file=sys.stderr)
        return None

    if message.author.id != bot_user_id:
        print("Error: That message was not sent by this bot.", file=sys.stderr)
        return None
    return message


async def run_terminal(
    dm_channel: discord.DMChannel, bot_user_id: int, default_history: int
) -> bool:
    history_count = max(1, min(default_history, 100))
    print_help()
    print()
    print(f"Recent messages (last {history_count}):")
    await show_history(dm_channel, bot_user_id, history_count)
    print()

    last_bot_message_id = await find_last_bot_message_id(dm_channel, bot_user_id)
    if last_bot_message_id is not None:
        print(f"Last bot message ID: {last_bot_message_id}")
    else:
        print("Last bot message ID: none")
    print("Enter /help for commands, /quit to exit.")
    configure_line_editing()

    while True:
        try:
            raw = await asyncio.to_thread(input, "dm> ")
        except asyncio.CancelledError:
            print()
            print("Exiting.")
            return True
        except (EOFError, KeyboardInterrupt):
            print()
            print("Exiting.")
            return True

        line = raw.strip()
        if not line:
            continue

        async def send_message(content: str) -> None:
            nonlocal last_bot_message_id
            if not content:
                print("Error: Message content cannot be empty.", file=sys.stderr)
                return
            try:
                message = await dm_channel.send(content)
            except Forbidden:
                print("Error: Forbidden to send message in this DM.", file=sys.stderr)
                return
            except HTTPException as exc:
                print(f"Error: HTTP error while sending message: {exc}", file=sys.stderr)
                return
            last_bot_message_id = message.id
            sent_text = normalize_content(message.content or "")
            if not sent_text:
                sent_text = "[empty]"
            print(f"Sent message {message.id}: {sent_text}")

        if not line.startswith("/"):
            await send_message(line)
            continue

        if line in {"/quit", "/exit"}:
            return True
        if line == "/help":
            print_help()
            continue

        if line.startswith("/send "):
            await send_message(line[6:].strip())
            continue

        if line.startswith("/list"):
            parts = line.split(maxsplit=1)
            requested = history_count
            if len(parts) == 2:
                try:
                    requested = int(parts[1].strip())
                except ValueError:
                    print("Error: /list count must be an integer.", file=sys.stderr)
                    continue
            await show_history(dm_channel, bot_user_id, requested)
            continue

        if line.startswith("/edit-last "):
            if last_bot_message_id is None:
                print("Error: No previous bot message to edit.", file=sys.stderr)
                continue
            new_content = line[len("/edit-last "):].strip()
            if not new_content:
                print("Error: New message content cannot be empty.", file=sys.stderr)
                continue
            message = await fetch_owned_message(
                dm_channel, last_bot_message_id, bot_user_id
            )
            if message is None:
                continue
            try:
                await message.edit(content=new_content)
                print(f"Edited message {message.id}")
            except Forbidden:
                print("Error: Forbidden to edit this message.", file=sys.stderr)
            except HTTPException as exc:
                print(f"Error: HTTP error while editing message: {exc}", file=sys.stderr)
            continue

        if line == "/delete-last":
            if last_bot_message_id is None:
                print("Error: No previous bot message to delete.", file=sys.stderr)
                continue
            message = await fetch_owned_message(
                dm_channel, last_bot_message_id, bot_user_id
            )
            if message is None:
                continue
            try:
                await message.delete()
                print(f"Deleted message {message.id}")
                last_bot_message_id = await find_last_bot_message_id(
                    dm_channel, bot_user_id
                )
            except Forbidden:
                print("Error: Forbidden to delete this message.", file=sys.stderr)
            except HTTPException as exc:
                print(f"Error: HTTP error while deleting message: {exc}", file=sys.stderr)
            continue

        if line.startswith("/edit "):
            parts = line.split(maxsplit=2)
            if len(parts) < 3:
                print("Usage: /edit <message_id> <new text>", file=sys.stderr)
                continue
            try:
                message_id = int(parts[1])
            except ValueError:
                print("Error: message_id must be an integer.", file=sys.stderr)
                continue
            new_content = parts[2].strip()
            if not new_content:
                print("Error: New message content cannot be empty.", file=sys.stderr)
                continue
            message = await fetch_owned_message(dm_channel, message_id, bot_user_id)
            if message is None:
                continue
            try:
                edited = await message.edit(content=new_content)
                last_bot_message_id = edited.id
                print(f"Edited message {edited.id}")
            except Forbidden:
                print("Error: Forbidden to edit this message.", file=sys.stderr)
            except HTTPException as exc:
                print(f"Error: HTTP error while editing message: {exc}", file=sys.stderr)
            continue

        if line.startswith("/delete "):
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                print("Usage: /delete <message_id>", file=sys.stderr)
                continue
            try:
                message_id = int(parts[1])
            except ValueError:
                print("Error: message_id must be an integer.", file=sys.stderr)
                continue
            message = await fetch_owned_message(dm_channel, message_id, bot_user_id)
            if message is None:
                continue
            try:
                await message.delete()
                print(f"Deleted message {message.id}")
                if last_bot_message_id == message.id:
                    last_bot_message_id = await find_last_bot_message_id(
                        dm_channel, bot_user_id
                    )
            except Forbidden:
                print("Error: Forbidden to delete this message.", file=sys.stderr)
            except HTTPException as exc:
                print(f"Error: HTTP error while deleting message: {exc}", file=sys.stderr)
            continue

        print("Unknown command. Use /help.", file=sys.stderr)


async def main() -> int:
    args = build_argparser().parse_args()
    token = args.token
    if not token:
        try:
            token = getpass.getpass("Bot token: ")
        except (EOFError, KeyboardInterrupt):
            print()
            print("Exiting.")
            return 130
    if not token:
        print("Error: No bot token provided.", file=sys.stderr)
        return 2

    user_id = prompt_for_user_id(args.user_id)
    if user_id is None:
        print("Exiting.")
        return 130

    intents = discord.Intents.none()
    intents.messages = True
    intents.dm_messages = True

    client = discord.Client(intents=intents)
    done = asyncio.get_running_loop().create_future()
    active_dm_channel_id: int | None = None

    @client.event
    async def on_ready():
        nonlocal active_dm_channel_id
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

            active_dm_channel_id = dm_channel.id
            print(f"Connected to DM with {user} (channel id: {dm_channel.id})")
            ok = await run_terminal(dm_channel, client.user.id, args.history)
            active_dm_channel_id = None
            done.set_result(ok)
        except Exception as exc:
            done.set_exception(exc)

    @client.event
    async def on_message(message: discord.Message):
        if active_dm_channel_id is None:
            return
        if message.channel.id != active_dm_channel_id:
            return
        if client.user is None:
            return
        if message.author.id == client.user.id:
            return
        print()
        print(f"[NEW] {format_message_line(message, client.user.id)}")
        line_buffer = ""
        if readline is not None:
            try:
                line_buffer = readline.get_line_buffer()
            except Exception:
                line_buffer = ""
        if line_buffer:
            print(f"dm> {line_buffer}", end="", flush=True)
        else:
            print("dm> ", end="", flush=True)

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
