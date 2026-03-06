# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Single-file Python script (`export_teams.py`) that exports Microsoft Teams 1:1 and group chats to HTML + JSON. It uses the Teams internal API (`teams.cloud.microsoft/api/chatsvc/`) directly via a bearer token extracted from the browser — no Azure app registration or admin consent needed.

## Running the script

```bash
# First time setup
python3 -m venv .venv
source .venv/bin/activate
pip install requests

# Run (token must be set in the environment)
export TEAMS_TOKEN="eyJ0eXAi..."   # from DevTools — see README for how to get it
export TEAMS_REGION=au             # optional, skips auto-detection
python export_teams.py
```

Output goes to `teams_backup/` in the current working directory.

```bash
# Download a single specific conversation by URL (no full list fetch needed)
export TEAMS_CONV_URL="https://teams.cloud.microsoft/api/chatsvc/au/v1/users/ME/conversations/19%3A...%40unq.gbl.spaces/messages"
python export_teams.py

# Rename existing folders using improved name detection (no token needed)
TEAMS_RENAME=1 python export_teams.py
```

## Architecture

Everything lives in `export_teams.py`. The flow is:

1. **Token loading** (`load_token`) — reads `TEAMS_TOKEN` env var, JWT-decodes it without verification to extract `upn`, `exp`, and `aud` for validation. Rejects Graph API tokens (wrong audience).

2. **Region detection** (`find_base_url`) — probes `https://teams.cloud.microsoft/api/chatsvc/{region}/v1` for `au`, `us`, `eu`, etc. until one returns 200. Can be overridden with `TEAMS_REGION`.

3. **Conversation listing** (`fetch_conversations`) — paginates via `_metadata.forwardLink` (newer) then walks `_metadata.backwardLink` (older/dormant) from the first page to catch all conversations. Deduplicates by conv_id. Filters out team channels by ID suffix (`CHANNEL_SUFFIXES` / `CHAT_SUFFIXES` constants).

4. **Resume** (`build_resume_map`) — scans `teams_backup/*/messages.json` at startup, reads `conversation.id` from each, and builds a `{conv_id: folder_path}` map. This means resume is keyed on conv_id, not folder name — folder renames don't break it.

5. **Message fetching** (`fetch_messages`) — paginates backwards via `_metadata.backwardLink` (oldest history first), then reverses the result list so output is chronological.

6. **Folder naming** (`chat_label` / `names_from_messages`) — collects unique sender names from messages preferring `fromDisplayNameInToken`, falling back to `imdisplayname` (common in older chats). Falls back further to `threadProperties.topic`, then conversation member metadata.

7. **Rate limiting** (`get`) — all HTTP calls go through this wrapper which retries on 429 (with `Retry-After` header respect and exponential backoff capped at 32s) and 5xx errors.

## Key constants

| Constant | Purpose |
|---|---|
| `OUTPUT_DIR` | Where `teams_backup/` is written (relative to cwd) |
| `CHANNEL_SUFFIXES` | ID suffixes that identify team channels to skip |
| `CHAT_SUFFIXES` | ID suffixes that identify 1:1 and group chats to keep |
| `SKIP_TYPES` | Message types filtered out of HTML output (system events, calls) |

## Teams internal API notes

- Base URL: `https://teams.cloud.microsoft/api/chatsvc/{region}/v1`
- Conversations: `GET /users/ME/conversations?view=msnp24Equivalent|supportsMessageProperties`
- Messages: `GET /users/ME/conversations/{encoded_id}/messages?startTime=1&pageSize=200`
- Tokens expire after ~1 hour — the script validates expiry on startup
- Sender display name priority: `fromDisplayNameInToken` → `imdisplayname` (older chats) → conversation metadata
