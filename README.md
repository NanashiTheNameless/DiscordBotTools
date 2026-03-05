# DiscordBotTools

Small standalone scripts for managing Discord bots and guilds.

## Requirements

- Python 3.10+
- Secure `discord.py` (`pip install git+https://github.com/NanashiTheNameless/discord.py`)
- A Discord bot token

## Setup

```bash
git clone https://github.com/NanashiTheNameless/DiscordBotTools
cd DiscordBotTools
pip install git+https://github.com/NanashiTheNameless/discord.py
```

## Available Scripts

### `Delete_Bot_DMs_With_User.py`

Delete this bot's messages in a DM channel with a specific user.

- `--token` (prompts if omitted)
- `--user-id` (prompts if omitted)
- `--sleep` delay between deletions (default: `0.3`)

Example:

```bash
python3 Delete_Bot_DMs_With_User.py --user-id 123456789012345678
```

### `Get_Guild_Owner.py`

Get owner information for a guild the bot can access.

- `--token` (prompts if omitted)
- `--guild-id` (prompts if omitted)

Example:

```bash
python3 Get_Guild_Owner.py --guild-id 123456789012345678
```

### `Leave_Guild.py`

Make the bot leave a guild.

- `--token` (prompts if omitted)
- `--guild-id` (prompts if omitted)

Example:

```bash
python3 Leave_Guild.py --guild-id 123456789012345678
```

### `List_Guild_Invites.py`

List active invites for a guild and optionally create a new invite.

- `--token` (prompts if omitted)
- `--guild-id` (prompts if omitted)
- `--format text|json|csv` (default: `text`)
- `--include-revoked`
- Invite creation options:
  `--create`, `--only-if-none`, `--channel-id`, `--max-age`, `--max-uses`,
  `--temporary`, `--unique`, `--reason`

Example:

```bash
python3 List_Guild_Invites.py --guild-id 123456789012345678 --format json
```

### `List_Guilds.py`

List all guilds the bot is in.

- `--token` (prompts if omitted)
- `--format text|json|csv` (default: `text`)
- `--include-counts`
- `--include-owner`

Example:

```bash
python3 List_Guilds.py --format json --include-owner
```

## Notes

- Run any script without flags to use interactive prompts.
- Make sure your bot has permissions required for the action.
- Never share your bot token.

## License

See [LICENSE.md](<https://github.com/NanashiTheNameless/DiscordBotTools/blob/main/LICENSE.md>).
