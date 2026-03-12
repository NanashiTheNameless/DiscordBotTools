#!/usr/bin/env python3.14
# This software is licensed under NNCL v1.3 see LICENSE.md for more info
# https://github.com/NanashiTheNameless/DiscordBotTools/blob/main/LICENSE.md

import argparse
import asyncio
import getpass
import os
import sys
from collections.abc import Awaitable, Callable
from typing import TypeVar

import discord  # pyright: ignore[reportMissingImports]
from discord.errors import (  # pyright: ignore[reportMissingImports]
    Forbidden,
    HTTPException,
    NotFound,
)

readline = None
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
        description="Delete this bot's messages in the DM channel with a specific user."
    )
    p.add_argument("--token", help="Bot token. If omitted, prompts.")
    p.add_argument("--user-id", type=int, help="Target user ID (prompts if omitted).")
    p.add_argument(
        "--sleep",
        type=float,
        default=0.0,
        help="Delay (seconds) between deletions. Default: 0.0",
    )
    p.add_argument(
        "--scan-limit",
        type=int,
        default=None,
        help="Only inspect this many most recent DM messages. Default: unlimited",
    )
    p.add_argument(
        "--before-message-id",
        type=int,
        help="Only inspect messages before this Discord message ID.",
    )
    p.add_argument(
        "--after-message-id",
        type=int,
        help="Only inspect messages after this Discord message ID.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print extra progress and retry information to stderr.",
    )
    return p


async def main() -> int:
    args = build_argparser().parse_args()
    verbose = build_verbose_printer(args.verbose)
    token = args.token
    if not token:
        try:
            token = prompt_token_with_mask("Bot token: ")
        except (EOFError, KeyboardInterrupt):
            print("Error: No bot token provided.", file=sys.stderr)
            return 2
    if not token:
        print("Error: No bot token provided.", file=sys.stderr)
        return 2
    if args.scan_limit is not None and args.scan_limit <= 0:
        print("Error: --scan-limit must be greater than zero.", file=sys.stderr)
        return 2

    user_id = args.user_id
    while user_id is None:
        try:
            raw = prompt_line("Target user ID: ").strip()
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
    stats = {"scanned": 0, "deleted": 0, "failed": 0}

    @client.event
    async def on_ready():
        print(f"Logged in as {client.user} (id: {client.user.id})")
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

            print(f"DM channel with {user} is {dm_channel.id}. Scanning messages...")
            if args.sleep > 0:
                verbose(f"Using a fixed {args.sleep:.3f}s delay between deletions.")

            history_before = (
                discord.Object(id=args.before_message_id)
                if args.before_message_id is not None
                else None
            )
            history_after = (
                discord.Object(id=args.after_message_id)
                if args.after_message_id is not None
                else None
            )
            verbose(
                "Scanning newest-first"
                f" with scan_limit={args.scan_limit or 'unlimited'},"
                f" before_message_id={args.before_message_id or 'latest'},"
                f" after_message_id={args.after_message_id or 'none'}."
            )

            async for message in dm_channel.history(
                limit=args.scan_limit,
                before=history_before,
                after=history_after,
                oldest_first=False,
            ):
                stats["scanned"] += 1
                if args.verbose and stats["scanned"] % 250 == 0:
                    verbose(
                        f"Scanned {stats['scanned']} messages; "
                        f"deleted {stats['deleted']}, failed {stats['failed']}."
                    )
                if message.author.id != client.user.id:
                    continue

                try:
                    await retry_http_request(
                        f"deleting message {message.id}",
                        message.delete,
                        attempts=4,
                        verbose=verbose,
                    )
                    stats["deleted"] += 1
                    if args.verbose:
                        verbose(f"Deleted message {message.id}.")
                    if args.sleep > 0:
                        await asyncio.sleep(args.sleep)  # be gentle with rate limits
                except NotFound:
                    stats["deleted"] += 1
                    if args.verbose:
                        verbose(
                            f"Message {message.id} was already gone; treating it as deleted."
                        )
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
        f"Done. Scanned {stats['scanned']} messages. Deleted {stats['deleted']} messages. "
        f"Failed to delete {stats['failed']} messages."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
