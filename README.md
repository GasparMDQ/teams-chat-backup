# Teams Chat Backup

Exports your Microsoft Teams 1:1 and group chats to readable HTML files and raw JSON.
Works with SSO — no Azure app registration or admin consent required.

---

## What it exports

| Included | Excluded |
|---|---|
| 1:1 personal chats | Team channel posts |
| Group chats (multi-person) | Meeting channel threads |

---

## Prerequisites

- Python 3.10+
- Access to [teams.microsoft.com](https://teams.microsoft.com) in a browser

---

## Setup (one time)

```bash
cd /path/to/this/folder
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install requests
```

---

## Step 1 — Get your token

Every person who wants to export their own chats needs to do this:

1. Open **[teams.microsoft.com](https://teams.microsoft.com)** in your browser and sign in
2. Open **DevTools**
   - Windows/Linux: `F12`
   - Mac: `Cmd + Option + I`
3. Click the **Network** tab
4. Click into **any chat conversation** and scroll up to trigger message loading
5. In the **filter box** at the top of the Network tab, type: `chatsvc`
6. Click any request that appears in the list
7. In the **Headers** panel on the right, find the `Authorization` header
8. Copy everything **after** `Bearer ` — this is your token (a long string starting with `eyJ...`)

> Tokens expire after ~1 hour. If you see `401` errors, repeat these steps to get a fresh token.

---

## Step 2 — Run

```bash
source .venv/bin/activate

export TEAMS_TOKEN="eyJ0eXAiOiJKV1Q..."    # paste your token here
python export_teams.py
```

**On Windows (PowerShell):**
```powershell
.venv\Scripts\activate
$env:TEAMS_TOKEN = "eyJ0eXAiOiJKV1Q..."
python export_teams.py
```

The script will auto-detect your region (`au`, `us`, `eu`, etc.). To set it manually:
```bash
export TEAMS_REGION=au    # use the region code from the URL you saw in DevTools
```

---

## Resuming an interrupted run

Just run the same command again. Chats that were already fully downloaded are skipped automatically. To re-download a specific chat, delete its folder inside `teams_backup/`.

---

## Downloading a specific chat by URL

If a conversation is missing from a full run, you can download it directly using its URL from DevTools:

```bash
export TEAMS_TOKEN="eyJ0eXAi..."
export TEAMS_CONV_URL="https://teams.cloud.microsoft/api/chatsvc/au/v1/users/ME/conversations/19%3A...%40unq.gbl.spaces/messages"
python export_teams.py
```

---

## Renaming existing folders

If older chats were saved with hash-based names, run this to rename them using sender names extracted from the saved messages (no token needed):

```bash
TEAMS_RENAME=1 python export_teams.py
```

---

## Output

```
teams_backup/
  Alice Smith_<id>/
    index.html       ← open in any browser to read the conversation
    messages.json    ← raw API data (useful for search or further processing)
  Project team_<id>/
    ...
  _index.json        ← summary of all chats and message counts
```

---

## Viewing your backup

```bash
python view_teams.py
```

Generates `teams_viewer.html` and opens it in your default browser. Features:

- Sidebar listing all chats sorted by message count
- Unified search across chat names and message content
- Light/dark theme toggle (preference saved across sessions)

To regenerate after a new backup run, just run the command again.

**Options:**

| Flag | Default | Description |
|---|---|---|
| `--dir PATH` | `./teams_backup` | Backup directory to read |
| `--output PATH` | `./teams_viewer.html` | Output file path |
| `--no-open` | — | Generate without opening browser |

---

## Troubleshooting

| Error | Fix |
|---|---|
| `No token found` | Make sure you ran `export TEAMS_TOKEN=...` in the same terminal session |
| `401 Unauthorized` | Token expired — grab a fresh one from DevTools |
| `This is a Graph API token` | Filter DevTools by `chatsvc`, not `graph.microsoft.com` |
| `Could not auto-detect region` | Set `export TEAMS_REGION=au` (or your region from the DevTools URL) |
| `429 Too Many Requests` | The script handles this automatically with backoff — just let it run |
| A specific chat is missing | Use `TEAMS_CONV_URL` to download it directly (see above) |
