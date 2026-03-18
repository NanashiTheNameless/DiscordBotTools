# DiscordBotTools

Small standalone scripts for managing Discord bots and guilds.

## Requirements

- Python 3.10+
- Secure `discord.py` (like <https://github.com/NanashiTheNameless/discord.py>)
- A Discord bot token

## Setup

```bash
git clone https://github.com/NanashiTheNameless/DiscordBotTools
cd DiscordBotTools
python3.14 -m pip install --upgrade git+https://github.com/NanashiTheNameless/discord.py
```

## Available Scripts

Common behavior across scripts:

- If `--token` is omitted, the script prompts for the bot token.
  In interactive POSIX terminals, input is shown as `*` characters.
  In fallback/non-interactive modes, input is hidden by `getpass` without `*` echo.
- If a required ID flag is omitted (`--user-id` / `--guild-id`), the script prompts for it.
- IDs must be numeric Discord snowflakes.
- Prompted input supports left/right cursor movement for inline editing when terminal/readline support is available.
- All scripts support `--verbose` for extra progress and retry information on `stderr`.
- Transient Discord HTTP failures on safe fetch/read operations are retried automatically.

### `Delete_Bot_DMs_With_User.py`

Delete the bot's messages in a DM channel with a specific user.

Flags:

- `--token <bot_token>`: Bot token to log in with. If omitted, prompts securely.
- `--user-id <user_id>`: Target user's ID. If omitted, prompts until valid numeric input.
- `--sleep <seconds>`: Delay between deleting each bot-authored message in that DM.
  Default is `0.0`.
- `--scan-limit <count>`: Only inspect this many most recent DM messages.
  Default is unlimited.
- `--before-message-id <message_id>`: Only inspect messages before this Discord message ID.
- `--after-message-id <message_id>`: Only inspect messages after this Discord message ID.
- `--verbose`: Print extra progress and retry information to `stderr`.

Notes:

- Only messages sent by the bot are deleted.
- Messages are processed newest-to-oldest.
- Discord DM history still has to be paginated by Discord's API.
  Use `--scan-limit`, `--before-message-id`, or `--after-message-id` to avoid crawling the entire conversation when you only need a slice.

Example:

```bash
python3.14 Delete_Bot_DMs_With_User.py --user-id 123456789012345678 --scan-limit 5000 --verbose
```

### `DM_As_Bot.py`

Interactive DM terminal as the bot for one user.

Flags:

- `--token <bot_token>`: Bot token to log in with. If omitted, prompts securely.
- `--user-id <user_id>`: Target user's ID. If omitted, prompts until valid numeric input.
- `--history <count>`: Number of recent DM messages shown on connect, and the default
  count used by `/list` with no argument. Default is `10`. Runtime display is clamped
  to `1-100`.
- `--verbose`: Print extra progress and retry information to `stderr`.

Behavior:

- New incoming DM messages from the target user are printed live while the terminal is open.
- Displayed messages wrap to the current terminal width.
- Message display preserves newlines and expands tabs for terminal output.
- Attachments are shown as:
  `[N attachment(s)]`
  followed by one `filename: url` line per attachment.
- Typed escapes in sends and edits are decoded before sending:
  `\n` for newline, `\t` for tab, `\\` for a literal backslash.

Commands inside the terminal:

- Plain text: send that text as a new DM.
- `/send <text>`: explicit send command (same effect as plain text).
- `/list [count]`: show recent messages (count is clamped to `1-100`).
- `/edit <message_id> <text>`: edit one of the bot's messages.
- `/delete <message_id>`: delete one of the bot's messages.
- `/edit-last <text>`: edit the most recent bot message found in that DM.
- `/delete-last`: delete the most recent bot message found in that DM.
- `/quit`, `/exit`: exit the terminal.
- `/help`: show command help.

Example:

```bash
python3.14 DM_As_Bot.py --user-id 123456789012345678
```

### `Get_Guild_Owner.py`

Get owner information for a guild the bot can access.

Flags:

- `--token <bot_token>`: Bot token to log in with. If omitted, prompts securely.
- `--guild-id <guild_id>`: Guild ID to inspect. If omitted, prompts until valid numeric input.
- `--verbose`: Print extra progress and retry information to `stderr`.

Output:

- Guild name and ID.
- Owner ID (and owner username if the user lookup succeeds).

Example:

```bash
python3.14 Get_Guild_Owner.py --guild-id 123456789012345678
```

### `Leave_Guild.py`

Make the bot leave a guild.

Flags:

- `--token <bot_token>`: Bot token to log in with. If omitted, prompts securely.
- `--guild-id <guild_id>`: Guild ID to leave. If omitted, prompts until valid numeric input.
- `--verbose`: Print extra progress and retry information to `stderr`.

Note:

- The bot must already be in the guild for this to succeed.

Example:

```bash
python3.14 Leave_Guild.py --guild-id 123456789012345678
```

### `List_Guild_Invites.py`

List active invites for a guild and optionally create a new invite.

Flags:

- `--token <bot_token>`: Bot token to log in with. If omitted, prompts securely.
- `--guild-id <guild_id>`: Guild ID to inspect. If omitted, prompts until valid numeric input.
- `--format <text|json|csv>`: Output format. Default: `text`.
- `--include-revoked`: Include invites marked as revoked (if Discord API returns them).
- `--verbose`: Print extra progress and retry information to `stderr`.

Invite creation flags:

- `--create`: Create a new invite in addition to listing invites.
- `--only-if-none`: Only create if there are currently no invites found.
  Has effect only when combined with `--create`.
- `--channel-id <channel_id>`: Channel to create the invite in.
  If omitted, script tries guild system channel, then first text channel, then first invite-capable channel.
- `--max-age <seconds>`: Invite lifetime in seconds. `0` means no expiration.
  Default: `0`.
- `--max-uses <count>`: Maximum uses. `0` means unlimited uses.
  Default: `0`.
- `--temporary`: Create a temporary-membership invite.
- `--unique`: Force a unique invite code instead of reusing similar existing invite settings.
- `--reason <text>`: Audit log reason used for invite creation.

Example:

```bash
python3.14 List_Guild_Invites.py --guild-id 123456789012345678 --format json
```

### `List_Guilds.py`

List all guilds the bot is in.

Flags:

- `--token <bot_token>`: Bot token to log in with. If omitted, prompts securely.
- `--format <text|json|csv>`: Output format. Default: `text`.
- `--include-counts`: Include `member_count` in output.
  This count may be approximate without privileged member intent.
- `--include-owner`: Include `owner_id` in output.
- `--verbose`: Print extra progress information to `stderr`.

Example:

```bash
python3.14 List_Guilds.py --format json --include-owner
```

### `List_Guild_Roles_Users.py`

List roles in a guild, then list users that have one selected role.

Flags:

- `--token <bot_token>`: Bot token to log in with. If omitted, prompts securely.
- `--guild-id <guild_id>`: Guild ID to inspect. If omitted, prompts until valid numeric input.
- `--role-id <role_id>`: Role ID to inspect. If omitted, script prints available roles and prompts.
- `--format <text|json|csv>`: Output format. Default: `text`.
- `--include-everyone`: Include `@everyone` in role listings and allow selecting it.
- `--include-bots`: Include bot users in member output.
- `--verbose`: Print extra progress and retry information to `stderr`.

Notes:

- The bot must have guild member access and Server Members Intent enabled to list role members reliably.

Example:

```bash
python3.14 List_Guild_Roles_Users.py --guild-id 123456789012345678
```

### `List_Guild_Users.py`

List users in a guild.

Flags:

- `--token <bot_token>`: Bot token to log in with. If omitted, prompts securely.
- `--guild-id <guild_id>`: Guild ID to inspect. If omitted, prompts until valid numeric input.
- `--format <text|json|csv>`: Output format. Default: `text`.
- `--include-bots`: Include bot users in output.
- `--include-roles`: Include each user's role IDs in output.
- `--verbose`: Print extra progress and retry information to `stderr`.

Notes:

- The bot must have guild member access and Server Members Intent enabled to list members reliably.

Example:

```bash
python3.14 List_Guild_Users.py --guild-id 123456789012345678 --format json
```

## Notes

- Run any script without flags to use interactive prompts.
- Make sure your bot has permissions required for the action.
- Prefer the secure prompt over passing `--token` directly on the command line.
- Never share your bot token.

## License

See [LICENSE.md](<https://github.com/NanashiTheNameless/DiscordBotTools/blob/main/LICENSE.md>).
