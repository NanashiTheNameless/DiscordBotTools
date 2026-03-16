#!/usr/bin/env python3.14
# This software is licensed under NNCL v1.3 see LICENSE.md for more info
# https://github.com/NanashiTheNameless/DiscordBotTools/blob/main/LICENSE.md

import argparse
import asyncio
import getpass
import os
import shutil
import sys
import textwrap
import threading
from collections.abc import Awaitable, Callable
from types import ModuleType
from typing import TypeVar

import discord  # pyright: ignore[reportMissingImports]
from discord.errors import (  # pyright: ignore[reportMissingImports]
    Forbidden,
    HTTPException,
    NotFound,
)

readline: ModuleType | None
try:
    import readline as _readline

    readline = _readline
except ImportError:
    readline = None

T = TypeVar("T")
RETRYABLE_HTTP_STATUSES = {429, 500, 502, 503, 504, 524}
TRANSIENT_HTTP_MARKERS = (
    "service unavailable",
    "upstream connect error",
    "disconnect/reset before headers",
    "reset reason: overflow",
    "server error",
    "bad gateway",
    "gateway timeout",
    "temporarily unavailable",
)


def build_verbose_printer(enabled: bool) -> Callable[[str], None]:
    def verbose(message: str) -> None:
        if enabled:
            print(f"[verbose] {message}", file=sys.stderr)

    return verbose


def is_retryable_http_exception(exc: HTTPException) -> bool:
    status = getattr(exc, "status", None)
    if status in RETRYABLE_HTTP_STATUSES:
        return True

    message = str(exc).lower()
    return any(marker in message for marker in TRANSIENT_HTTP_MARKERS)


async def retry_http_request(
    label: str,
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 5,
    base_delay: float = 1.0,
    max_delay: float = 8.0,
    verbose: Callable[[str], None] | None = None,
) -> T:
    last_exc: HTTPException | None = None
    for attempt in range(1, attempts + 1):
        try:
            result = await operation()
            if attempt > 1 and verbose is not None:
                verbose(f"{label} succeeded on attempt {attempt}/{attempts}.")
            return result
        except HTTPException as exc:
            last_exc = exc
            if attempt >= attempts or not is_retryable_http_exception(exc):
                raise

            delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
            status = getattr(exc, "status", "?")
            print(
                f"Warning: {label} failed with HTTP {status} on attempt "
                f"{attempt}/{attempts}; retrying in {delay:.1f}s.",
                file=sys.stderr,
            )
            await asyncio.sleep(delay)

    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"retry_http_request exhausted attempts for {label}")


def configure_line_editing() -> None:
    if readline is None:
        return
    try:
        readline.parse_and_bind("set editing-mode emacs")
        readline.parse_and_bind('"\\e[D": backward-char')
        readline.parse_and_bind('"\\e[C": forward-char')
        readline.parse_and_bind('"\\e[3~": delete-char')
    except Exception:
        return


def prompt_line(prompt: str) -> str:
    configure_line_editing()
    return input(prompt)


def prompt_token_with_mask(prompt: str = "Bot token: ") -> str:
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return getpass.getpass(prompt)

    try:
        import termios
        import tty
    except ImportError:
        return getpass.getpass(prompt)

    fd = sys.stdin.fileno()
    original_settings = termios.tcgetattr(fd)
    chars: list[str] = []
    cursor = 0

    def render() -> None:
        masked = "*" * len(chars)
        sys.stdout.write("\r" + prompt + masked + "\x1b[K")
        move_left = len(chars) - cursor
        if move_left > 0:
            sys.stdout.write(f"\x1b[{move_left}D")
        sys.stdout.flush()

    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        tty.setcbreak(fd)
        while True:
            raw = os.read(fd, 1)
            if not raw:
                raise EOFError
            char = raw.decode(errors="ignore")

            if char in ("\r", "\n"):
                # Drain any trailing CR/LF so the next prompt does not auto-submit.
                try:
                    termios.tcflush(fd, termios.TCIFLUSH)
                except Exception:
                    pass
                sys.stdout.write("\r\n")
                sys.stdout.flush()
                return "".join(chars)
            if char == "\x03":
                raise KeyboardInterrupt
            if char == "\x04":
                raise EOFError
            if char in ("\x7f", "\b"):
                if cursor > 0:
                    del chars[cursor - 1]
                    cursor -= 1
                    render()
                continue
            if char == "\x1b":
                seq1 = os.read(fd, 1)
                if seq1 != b"[":
                    continue
                seq2 = os.read(fd, 1)
                if seq2 == b"D":
                    if cursor > 0:
                        cursor -= 1
                        render()
                    continue
                if seq2 == b"C":
                    if cursor < len(chars):
                        cursor += 1
                        render()
                    continue
                if seq2 == b"3":
                    seq3 = os.read(fd, 1)
                    if seq3 == b"~" and cursor < len(chars):
                        del chars[cursor]
                        render()
                    continue
                continue
            if char.isprintable():
                chars.insert(cursor, char)
                cursor += 1
                render()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original_settings)


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
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print extra progress and retry information to stderr.",
    )
    return p


def prompt_for_user_id(initial_value: int | None) -> int | None:
    user_id = initial_value
    while user_id is None:
        try:
            raw = prompt_line("Target user ID: ").strip()
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
    return content.replace("\r\n", "\n").replace("\r", "\n")


def decode_typed_escapes(text: str) -> str:
    decoded: list[str] = []
    index = 0
    replacements = {
        "\\": "\\",
        "n": "\n",
        "t": "\t",
    }

    while index < len(text):
        char = text[index]
        if char != "\\" or index + 1 >= len(text):
            decoded.append(char)
            index += 1
            continue

        escaped = replacements.get(text[index + 1])
        if escaped is None:
            decoded.append(char)
            index += 1
            continue

        decoded.append(escaped)
        index += 2

    return "".join(decoded)


def get_terminal_columns() -> int:
    return max(60, shutil.get_terminal_size(fallback=(100, 24)).columns)


def expand_tabs_for_display(text: str, *, start_column: int, tabsize: int = 8) -> str:
    expanded: list[str] = []
    column = start_column
    for char in text:
        if char == "\t":
            spaces = tabsize - (column % tabsize)
            expanded.append(" " * spaces)
            column += spaces
            continue
        expanded.append(char)
        column += 1
    return "".join(expanded)


def format_text_block(header: str, content: str) -> list[str]:
    content_width = max(20, get_terminal_columns() - len(header))
    continuation = " " * len(header)
    rendered: list[str] = []

    for logical_line in normalize_content(content).split("\n"):
        expanded_line = expand_tabs_for_display(logical_line, start_column=len(header))
        wrapped = textwrap.wrap(
            expanded_line,
            width=content_width,
            replace_whitespace=False,
            drop_whitespace=False,
            break_long_words=False,
            break_on_hyphens=False,
        )
        if not wrapped:
            wrapped = [""]

        for chunk in wrapped:
            line_prefix = header if not rendered else continuation
            rendered.append(line_prefix + chunk)

    return rendered or [header]


def format_message_lines(
    message: discord.Message, bot_user_id: int, *, prefix: str = ""
) -> list[str]:
    author = "bot" if message.author.id == bot_user_id else str(message.author)
    content_parts: list[str] = []
    content = normalize_content(message.content or "")
    if content:
        content_parts.append(content)
    if message.attachments:
        content_parts.append(f"[{len(message.attachments)} attachment(s)]")
        for index, attachment in enumerate(message.attachments, start=1):
            filename = attachment.filename or f"attachment-{index}"
            filename = filename.replace("\r", " ").replace("\n", " ")
            content_parts.append(f"{filename}: {attachment.url}")
    content = "\n".join(content_parts)
    if not content:
        content = "[empty]"

    header = f"{prefix}{message.id}  {author}: "
    return format_text_block(header, content)


def print_help() -> None:
    print("Commands:")
    print("  /help                      Show this help")
    print("  /list [count]              Show recent DM messages")
    print("  /send <text>               Send a message")
    print("  /edit <message_id> <text>  Edit one of the bot's messages")
    print("  /delete <message_id>       Delete one of the bot's messages")
    print("  /edit-last <text>          Edit the last bot message")
    print("  /delete-last               Delete the last bot message")
    print("  /quit, /exit               Exit")
    print("Tip: entering plain text (without a leading /) sends that text.")
    print("Tip: use \\n, \\t, and \\\\ in sends and edits for escapes.")


async def read_input(prompt: str) -> str:
    loop = asyncio.get_running_loop()
    result: asyncio.Future[str] = loop.create_future()

    def resolve(value: str) -> None:
        if not result.done():
            result.set_result(value)

    def reject(exc: BaseException) -> None:
        if not result.done():
            result.set_exception(exc)

    def worker() -> None:
        try:
            value = prompt_line(prompt)
        except BaseException as exc:
            try:
                loop.call_soon_threadsafe(reject, exc)
            except RuntimeError:
                return
            return
        try:
            loop.call_soon_threadsafe(resolve, value)
        except RuntimeError:
            return

    threading.Thread(target=worker, daemon=True).start()
    return await result


async def show_history(
    dm_channel: discord.DMChannel,
    bot_user_id: int,
    limit: int,
    verbose: Callable[[str], None],
) -> None:
    count = max(1, min(limit, 100))

    async def load_messages() -> list[discord.Message]:
        return [message async for message in dm_channel.history(limit=count)]

    try:
        # Fetch latest messages, then print oldest->newest within that window.
        messages = await retry_http_request(
            "reading DM history",
            load_messages,
            verbose=verbose,
        )
        messages.reverse()
    except HTTPException as exc:
        print(f"Error: HTTP error while reading history: {exc}", file=sys.stderr)
        return

    if not messages:
        print("(No messages in history)")
        return

    for message in messages:
        for line in format_message_lines(message, bot_user_id):
            print(line)


async def find_last_bot_message_id(
    dm_channel: discord.DMChannel,
    bot_user_id: int,
    verbose: Callable[[str], None],
) -> int | None:
    async def find_message() -> int | None:
        async for message in dm_channel.history(limit=100):
            if message.author.id == bot_user_id:
                return message.id
        return None

    try:
        return await retry_http_request(
            "finding last bot DM message",
            find_message,
            verbose=verbose,
        )
    except HTTPException:
        return None


async def fetch_owned_message(
    dm_channel: discord.DMChannel,
    message_id: int,
    bot_user_id: int,
    verbose: Callable[[str], None],
) -> discord.Message | None:
    try:
        message = await retry_http_request(
            f"fetching message {message_id}",
            lambda: dm_channel.fetch_message(message_id),
            verbose=verbose,
        )
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
    dm_channel: discord.DMChannel,
    bot_user_id: int,
    default_history: int,
    verbose: Callable[[str], None],
) -> bool:
    history_count = max(1, min(default_history, 100))
    print_help()
    print()
    print(f"Recent messages (last {history_count}):")
    await show_history(dm_channel, bot_user_id, history_count, verbose)
    print()

    last_bot_message_id = await find_last_bot_message_id(
        dm_channel, bot_user_id, verbose
    )
    if last_bot_message_id is not None:
        print(f"Last bot message ID: {last_bot_message_id}")
    else:
        print("Last bot message ID: none")
    print("Enter /help for commands, /quit or /exit to exit.")
    configure_line_editing()

    while True:
        try:
            raw = await read_input("dm> ")
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
            content = decode_typed_escapes(content)
            try:
                message = await dm_channel.send(content)
            except Forbidden:
                print("Error: Forbidden to send message in this DM.", file=sys.stderr)
                return
            except HTTPException as exc:
                print(
                    f"Error: HTTP error while sending message: {exc}", file=sys.stderr
                )
                return
            last_bot_message_id = message.id
            sent_text = message.content or "[empty]"
            for line in format_text_block(f"Sent message {message.id}: ", sent_text):
                print(line)

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
            await show_history(dm_channel, bot_user_id, requested, verbose)
            continue

        if line.startswith("/edit-last "):
            if last_bot_message_id is None:
                print("Error: No previous bot message to edit.", file=sys.stderr)
                continue
            new_content = line[len("/edit-last ") :].strip()
            if not new_content:
                print("Error: New message content cannot be empty.", file=sys.stderr)
                continue
            new_content = decode_typed_escapes(new_content)
            message = await fetch_owned_message(
                dm_channel, last_bot_message_id, bot_user_id, verbose
            )
            if message is None:
                continue
            last_editable_message: discord.Message = message
            try:
                await retry_http_request(
                    f"editing message {last_editable_message.id}",
                    lambda: last_editable_message.edit(content=new_content),
                    verbose=verbose,
                )
                print(f"Edited message {last_editable_message.id}")
            except Forbidden:
                print("Error: Forbidden to edit this message.", file=sys.stderr)
            except HTTPException as exc:
                print(
                    f"Error: HTTP error while editing message: {exc}", file=sys.stderr
                )
            continue

        if line == "/delete-last":
            if last_bot_message_id is None:
                print("Error: No previous bot message to delete.", file=sys.stderr)
                continue
            message = await fetch_owned_message(
                dm_channel, last_bot_message_id, bot_user_id, verbose
            )
            if message is None:
                continue
            try:
                await retry_http_request(
                    f"deleting message {message.id}",
                    message.delete,
                    attempts=4,
                    verbose=verbose,
                )
                print(f"Deleted message {message.id}")
                last_bot_message_id = await find_last_bot_message_id(
                    dm_channel, bot_user_id, verbose
                )
            except NotFound:
                print(f"Deleted message {message.id}")
                last_bot_message_id = await find_last_bot_message_id(
                    dm_channel, bot_user_id, verbose
                )
            except Forbidden:
                print("Error: Forbidden to delete this message.", file=sys.stderr)
            except HTTPException as exc:
                print(
                    f"Error: HTTP error while deleting message: {exc}", file=sys.stderr
                )
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
            new_content = decode_typed_escapes(new_content)
            message = await fetch_owned_message(
                dm_channel, message_id, bot_user_id, verbose
            )
            if message is None:
                continue
            target_editable_message: discord.Message = message
            try:
                edited = await retry_http_request(
                    f"editing message {target_editable_message.id}",
                    lambda: target_editable_message.edit(content=new_content),
                    verbose=verbose,
                )
                last_bot_message_id = edited.id
                print(f"Edited message {edited.id}")
            except Forbidden:
                print("Error: Forbidden to edit this message.", file=sys.stderr)
            except HTTPException as exc:
                print(
                    f"Error: HTTP error while editing message: {exc}", file=sys.stderr
                )
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
            message = await fetch_owned_message(
                dm_channel, message_id, bot_user_id, verbose
            )
            if message is None:
                continue
            try:
                await retry_http_request(
                    f"deleting message {message.id}",
                    message.delete,
                    attempts=4,
                    verbose=verbose,
                )
                print(f"Deleted message {message.id}")
                if last_bot_message_id == message.id:
                    last_bot_message_id = await find_last_bot_message_id(
                        dm_channel, bot_user_id, verbose
                    )
            except NotFound:
                print(f"Deleted message {message.id}")
                if last_bot_message_id == message.id:
                    last_bot_message_id = await find_last_bot_message_id(
                        dm_channel, bot_user_id, verbose
                    )
            except Forbidden:
                print("Error: Forbidden to delete this message.", file=sys.stderr)
            except HTTPException as exc:
                print(
                    f"Error: HTTP error while deleting message: {exc}", file=sys.stderr
                )
            continue

        print("Unknown command. Use /help.", file=sys.stderr)


async def main() -> int:
    args = build_argparser().parse_args()
    verbose = build_verbose_printer(args.verbose)
    token = args.token
    if not token:
        try:
            token = prompt_token_with_mask("Bot token: ")
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
        print(f"Logged in as {client.user} (id: {client.user.id})")  # type: ignore
        try:
            try:
                verbose(f"Fetching user {user_id}.")
                user = await retry_http_request(
                    "fetching target user",
                    lambda: client.fetch_user(user_id),
                    verbose=verbose,
                )
            except NotFound:
                print("Error: Target user not found.", file=sys.stderr)
                done.set_result(False)
                return
            except HTTPException as exc:
                print(f"Error: HTTP error while fetching user: {exc}", file=sys.stderr)
                done.set_result(False)
                return

            try:
                verbose(f"Resolving DM channel with user {user_id}.")
                dm_channel = await retry_http_request(
                    "creating or fetching DM channel",
                    user.create_dm,
                    verbose=verbose,
                )
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
            ok = await run_terminal(
                dm_channel,
                client.user.id,  # type: ignore[arg-type]
                args.history,
                verbose,
            )
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
        for line in format_message_lines(message, client.user.id, prefix="[NEW] "):
            print(line)
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
