#!/usr/bin/env python3.14
# This software is licensed under NNCL v1.4 see LICENSE.md for more info
# https://github.com/NanashiTheNameless/DiscordBotTools/blob/main/LICENSE.md

import argparse
import asyncio
import getpass
import json
import os
import sys
from collections.abc import Awaitable, Callable
from typing import TypedDict, TypeVar

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


class GuildRecord(TypedDict):
    id: int
    name: str


class MemberRecord(TypedDict):
    id: int
    tag: str
    name: str
    display_name: str
    bot: bool
    role_ids: list[int]


class State(TypedDict):
    guild: GuildRecord | None
    members: list[MemberRecord]


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
    p = argparse.ArgumentParser(description="List users in a Discord guild.")
    p.add_argument("--token", help="Bot token. If omitted, prompts.")
    p.add_argument(
        "--guild-id", type=int, help="Target guild (server) ID (prompts if omitted)."
    )
    p.add_argument(
        "--format",
        choices=["text", "json", "csv"],
        default="text",
        help="Output format.",
    )
    p.add_argument(
        "--include-bots",
        action="store_true",
        help="Include bot users in output.",
    )
    p.add_argument(
        "--include-roles",
        action="store_true",
        help="Include each user's role IDs in output.",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print extra progress and retry information to stderr.",
    )
    return p


async def fetch_all_members(
    guild: discord.Guild,
    verbose: Callable[[str], None],
) -> list[discord.Member]:
    if guild.chunked and guild.members:
        verbose(
            f"Guild member cache already loaded ({len(guild.members)} member record(s))."
        )
        return list(guild.members)

    try:
        verbose(f"Chunking members for guild {guild.id}.")
        await retry_http_request(
            "chunking guild members",
            lambda: guild.chunk(cache=True),
            verbose=verbose,
        )
        if guild.members:
            return list(guild.members)
    except Forbidden:
        raise
    except HTTPException:
        # Fall back to explicit fetch_members pagination.
        pass

    verbose(f"Falling back to paginated member fetch for guild {guild.id}.")

    async def do_fetch() -> list[discord.Member]:
        fetched_members: list[discord.Member] = []
        async for member in guild.fetch_members(limit=None):
            fetched_members.append(member)
        return fetched_members

    return await retry_http_request(
        "fetching guild members",
        do_fetch,
        verbose=verbose,
    )


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

    guild_id = args.guild_id
    while guild_id is None:
        try:
            raw = prompt_line("Target guild ID: ").strip()
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
    intents.members = True

    client = discord.Client(intents=intents)
    done = asyncio.get_running_loop().create_future()
    state: State = {
        "guild": None,
        "members": [],
    }

    @client.event
    async def on_ready():
        try:
            verbose(f"Logged in as {client.user} (id: {client.user.id})")
            guild = client.get_guild(guild_id)
            if guild is None:
                try:
                    verbose(f"Fetching guild {guild_id} from the API.")
                    guild = await retry_http_request(
                        "fetching guild",
                        lambda: client.fetch_guild(guild_id),
                        verbose=verbose,
                    )
                except NotFound:
                    print(f"Error: Guild {guild_id} not found.", file=sys.stderr)
                    done.set_result(False)
                    return
                except Forbidden:
                    print("Error: Bot cannot access that guild.", file=sys.stderr)
                    done.set_result(False)
                    return
                except HTTPException as exc:
                    print(
                        f"Error: HTTP error while fetching guild: {exc}",
                        file=sys.stderr,
                    )
                    done.set_result(False)
                    return
            else:
                verbose(f"Using cached guild {guild.name} ({guild.id}).")

            try:
                members = await fetch_all_members(guild, verbose)
            except Forbidden:
                print(
                    "Error: Missing permission or intent for member listing. "
                    "Enable Server Members Intent for the bot.",
                    file=sys.stderr,
                )
                done.set_result(False)
                return
            except HTTPException as exc:
                print(
                    f"Error: HTTP error while fetching guild members: {exc}",
                    file=sys.stderr,
                )
                done.set_result(False)
                return

            member_records: list[MemberRecord] = []
            for member in members:
                if not args.include_bots and member.bot:
                    continue
                member_records.append(
                    {
                        "id": member.id,
                        "tag": str(member),
                        "name": member.name,
                        "display_name": member.display_name,
                        "bot": member.bot,
                        "role_ids": [role.id for role in member.roles],
                    }
                )

            member_records.sort(key=lambda m: ((m["name"] or "").lower(), m["id"]))
            state["guild"] = {"id": guild.id, "name": guild.name}
            state["members"] = member_records
            done.set_result(True)
        except Exception as exc:
            done.set_exception(exc)

    async def run() -> int:
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

    guild_info = state["guild"]
    if guild_info is None:
        print("Error: Guild information was not loaded.", file=sys.stderr)
        return 1
    members = list(state["members"])

    if args.format == "json":
        payload = {
            "guild": guild_info,
            "users": [
                {
                    "id": member["id"],
                    "tag": member["tag"],
                    "name": member["name"],
                    "display_name": member["display_name"],
                    "bot": member["bot"],
                    **({"role_ids": member["role_ids"]} if args.include_roles else {}),
                }
                for member in members
            ],
        }
        json.dump(payload, sys.stdout, indent=2)
        print()
    elif args.format == "csv":
        headers = ["user_id", "user_tag", "user_name", "display_name", "is_bot"]
        if args.include_roles:
            headers.append("role_ids")
        print(",".join(headers))
        for member in members:
            row = [
                str(member["id"]),
                str(member["tag"]).replace(",", " "),
                str(member["name"]).replace(",", " "),
                str(member["display_name"]).replace(",", " "),
                str(member["bot"]),
            ]
            if args.include_roles:
                row.append("|".join(str(role_id) for role_id in member["role_ids"]))
            print(",".join(row))
    else:
        print(f"Guild: {guild_info['name']} ({guild_info['id']})")
        print(f"Users: {len(members)}")
        if not members:
            print("No users found.")
        else:
            for member in members:
                parts = [f"{member['tag']} ({member['id']})"]
                if member["display_name"] and member["display_name"] != member["name"]:
                    parts.append(f"display_name={member['display_name']}")
                if member["bot"]:
                    parts.append("bot=true")
                if args.include_roles:
                    parts.append(
                        "role_ids="
                        + "|".join(str(role_id) for role_id in member["role_ids"])
                    )
                print(" - " + "  ".join(parts))

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
