#!/usr/bin/env python3.14
# This software is licensed under NNCL v1.3 see LICENSE.md for more info
# https://github.com/NanashiTheNameless/DiscordBotTools/blob/main/LICENSE.md

import argparse
import asyncio
import getpass
import json
import os
import sys
from collections.abc import Awaitable, Callable
from datetime import timedelta
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
        description="List active invite links for a Discord guild (server), optionally create one."
    )
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
        "--include-revoked",
        action="store_true",
        help="Also show invites marked as revoked (API seldom returns these).",
    )

    p.add_argument(
        "--create",
        action="store_true",
        help="Create a new invite (use --only-if-none to create only when there are no active invites).",
    )
    p.add_argument(
        "--only-if-none",
        action="store_true",
        help="When used with --create, only create if no active invites exist.",
    )
    p.add_argument(
        "--channel-id",
        type=int,
        help="Channel ID to create the invite in. If omitted, tries system channel or first text channel.",
    )
    p.add_argument(
        "--max-age",
        type=int,
        default=0,
        help="Invite lifetime in seconds (0 = never expires). Default: 0.",
    )
    p.add_argument(
        "--max-uses", type=int, default=0, help="Max uses (0 = unlimited). Default: 0."
    )
    p.add_argument(
        "--temporary",
        action="store_true",
        help="Grant temporary membership (kicks on disconnect unless role is added).",
    )
    p.add_argument(
        "--unique",
        action="store_true",
        help="Always create a unique invite code even if one with similar settings exists.",
    )
    p.add_argument(
        "--reason", default=None, help="Audit log reason for creating the invite."
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print extra progress and retry information to stderr.",
    )
    return p


def invite_record(inv: discord.Invite) -> dict:
    expires_at = None
    try:
        if inv.max_age and inv.max_age > 0 and inv.created_at:
            expires_at = inv.created_at + timedelta(seconds=inv.max_age)
    except Exception:
        expires_at = None

    return {
        "code": inv.code,
        "url": inv.url,
        "channel_id": getattr(inv.channel, "id", None),
        "channel_name": getattr(inv.channel, "name", None),
        "inviter_id": getattr(inv.inviter, "id", None),
        "inviter_name": (
            getattr(inv.inviter, "name", None)
            if getattr(inv, "inviter", None)
            else None
        ),
        "uses": inv.uses,
        "max_uses": inv.max_uses,
        "temporary": inv.temporary,
        "revoked": getattr(inv, "revoked", False),
        "max_age_seconds": inv.max_age,
        "created_at": inv.created_at.isoformat() if inv.created_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


async def choose_channel_for_invite(
    guild: discord.Guild,
    preferred_id: int | None,
    verbose: Callable[[str], None],
) -> discord.abc.GuildChannel | None:
    if preferred_id:

        async def fetch_preferred_channel() -> discord.abc.GuildChannel | None:
            fetched_channel = await guild.fetch_channel(preferred_id)
            if isinstance(fetched_channel, discord.Thread):
                return None
            return fetched_channel

        try:
            ch: discord.abc.GuildChannel | None = guild.get_channel(preferred_id)
            if ch is None:
                verbose(f"Fetching preferred invite channel {preferred_id}.")
                ch = await retry_http_request(
                    "fetching preferred invite channel",
                    fetch_preferred_channel,
                    verbose=verbose,
                )
            return ch
        except (NotFound, Forbidden, HTTPException):
            return None
    system_channel = guild.system_channel
    if system_channel is not None:
        verbose(f"Using system channel {system_channel.id} for invite creation.")
        return system_channel
    for ch in sorted(guild.text_channels, key=lambda c: (c.position, c.id)):
        if ch is None:
            continue
        verbose(f"Using text channel {ch.id} for invite creation.")
        return ch
    for ch in guild.channels:
        if hasattr(ch, "create_invite"):
            verbose(
                f"Using fallback channel {getattr(ch, 'id', 'unknown')} for invite creation."
            )
            return ch
    return None


def prompt_for_int(prompt_text: str) -> int | None:
    while True:
        try:
            raw = prompt_line(prompt_text).strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if not raw:
            continue
        try:
            return int(raw)
        except ValueError:
            print("Please enter digits only.", file=sys.stderr)


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
    if guild_id is None:
        guild_id = prompt_for_int("Guild ID: ")
    if guild_id is None:
        print("Error: No guild ID provided.", file=sys.stderr)
        return 2

    intents = discord.Intents.none()
    intents.guilds = True

    client = discord.Client(intents=intents)
    done = asyncio.get_running_loop().create_future()
    results = {"guild_id": guild_id, "invites": [], "created_invite": None}

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
                except HTTPException:
                    guild = None
            else:
                verbose(f"Using cached guild {guild.name} ({guild.id}).")

            if guild is None:
                print(
                    "Error: Bot is not in that guild or cannot access it.",
                    file=sys.stderr,
                )
                done.set_result(False)
                return

            invites = []
            try:
                verbose(f"Fetching invites for guild {guild.id}.")
                invites = await retry_http_request(
                    "fetching guild invites",
                    guild.invites,
                    verbose=verbose,
                )
            except Forbidden:
                invites = []
            except HTTPException as e:
                print(f"Error: HTTP error when fetching invites: {e}", file=sys.stderr)
            else:
                verbose(f"Fetched {len(invites)} invite(s).")

            should_create = args.create and (not args.only_if_none or len(invites) == 0)
            created_rec = None
            if should_create:
                channel = await choose_channel_for_invite(
                    guild, args.channel_id, verbose
                )
                if channel is None:
                    print(
                        "Error: Could not resolve a channel to create an invite in.",
                        file=sys.stderr,
                    )
                else:
                    try:
                        verbose(f"Creating invite in channel {channel.id}.")
                        new_inv = await channel.create_invite(
                            max_age=args.max_age,
                            max_uses=args.max_uses,
                            temporary=args.temporary,
                            unique=args.unique,
                            reason=args.reason,
                        )
                        created_rec = invite_record(new_inv)
                        invites.append(new_inv)
                    except Forbidden:
                        print(
                            "Error: Forbidden creating invite. Ensure the bot has CREATE_INSTANT_INVITE on that channel.",
                            file=sys.stderr,
                        )
                    except HTTPException as e:
                        print(
                            f"Error: HTTP error when creating invite: {e}",
                            file=sys.stderr,
                        )

            for inv in invites:
                rec = invite_record(inv)
                if not args.include_revoked and rec.get("revoked"):
                    continue
                results["invites"].append(rec)

            if created_rec:
                results["created_invite"] = created_rec

            results["invites"].sort(
                key=lambda r: (r.get("channel_name") or "", r.get("code") or "")
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

    fmt = args.format
    invites = results["invites"]
    created = results["created_invite"]

    if fmt == "json":
        out = {"created_invite": created, "invites": invites}
        json.dump(out, sys.stdout, indent=2)
        print()
    elif fmt == "csv":
        headers = [
            "url",
            "code",
            "channel_id",
            "channel_name",
            "inviter_id",
            "inviter_name",
            "uses",
            "max_uses",
            "temporary",
            "revoked",
            "max_age_seconds",
            "created_at",
            "expires_at",
        ]
        print(",".join(headers))
        for r in invites:
            row = [
                r.get("url") or "",
                r.get("code") or "",
                str(r.get("channel_id") or ""),
                (r.get("channel_name") or "").replace(",", " "),
                str(r.get("inviter_id") or ""),
                (r.get("inviter_name") or "").replace(",", " "),
                str(r.get("uses") or 0),
                str(r.get("max_uses") or 0),
                str(bool(r.get("temporary"))),
                str(bool(r.get("revoked"))),
                str(r.get("max_age_seconds") or 0),
                r.get("created_at") or "",
                r.get("expires_at") or "",
            ]
            print(",".join(row))
        if created:
            sys.stderr.write(f"Created invite: {created['url']}\n")
    else:
        if created:
            print(f"Created invite: {created['url']}")
        if not invites:
            print("No active invites found.")
        else:
            for r in invites:
                line = f"{r['url']}  channel={r.get('channel_name')} uses={r.get('uses')}/{r.get('max_uses') or '∞'}"
                if r.get("expires_at"):
                    line += f" expires_at={r['expires_at']}"
                print(" • " + line)

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        raise SystemExit(130)
