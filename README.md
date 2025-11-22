# DiscordBotTools

This repository contains several Python scripts of mine for managing Discord bots and servers.

(Docs are written by AI because im too lazy, these are just for myself anyways)

Each script is standalone and can be run independently.

Below is documentation for each script and instructions on how to use them.

## Prerequisites

- Python 3.7+
- `discord.py` library (install with `pip install discord.py`)
- Your Discord bot token

## Scripts

### 1. Delete_Bot_DMs_With_User.py

Deletes this bot's messages in the DM channel with a specific user.

- Prompts for token (or use `--token`).
- Prompts for user ID if `--user-id` is not provided.
- Throttle deletion with `--sleep` (seconds, default 0.3).

**Usage:**

```bash
python3 Delete_Bot_DMs_With_User.py --user-id 123456789012345678
# or run without flags and fill prompts
```

### 2. List_Guild_Invites.py

Lists active invites for a guild and can optionally create one.

- Prompts for token (or use `--token`).
- Prompts for guild ID if `--guild-id` is not provided.
- Output formats: `--format text|json|csv` (default text).
- Optional flags: `--include-revoked`, `--create`, `--only-if-none`, `--channel-id`, `--max-age`, `--max-uses`, `--temporary`, `--unique`, `--reason`.

**Usage:**

```bash
python3 List_Guild_Invites.py --guild-id 123456789012345678 --format json
# or run without flags and fill prompts
```

### 3. List_Guilds.py

Lists all guilds (servers) your bot is in.

- Prompts for token (or use `--token`).
- Output formats: `--format text|json|csv` (default text).
- Optional flags: `--include-counts`, `--include-owner`.

**Usage:**

```bash
python3 List_Guilds.py --format json --include-owner
# or run without flags and fill prompts
```

## General Instructions

1. Clone this repository:

   ```bash
   git clone <repo-url>
   cd DiscordBotTools
   ```

2. Install dependencies:

   ```bash
   pip install discord.py
   ```

3. Run the desired script as shown above.

## Notes

- Make sure your bot has the necessary permissions for each operation.
- Never share your bot token publicly.

## License

See [LICENSE.md](<./LICENSE.md>) for license information.
