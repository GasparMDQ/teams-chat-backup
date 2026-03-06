#!/usr/bin/env python3
"""
Microsoft Teams Chat Backup Tool

Exports 1:1 and group chats using your existing SSO browser session.
Supports resuming interrupted runs, rate-limit backoff, and chat-only filtering.

No Azure app registration or admin consent required.

HOW TO GET YOUR TOKEN
---------------------
1. Open https://teams.microsoft.com in your browser (already signed in via SSO)
2. Open DevTools: F12 (Windows/Linux) or Cmd+Option+I (Mac)
3. Go to the Network tab
4. Click into any chat conversation and scroll to load messages
5. In the filter box type: chatsvc
6. Click any request -> Headers panel
7. Find the Authorization header, copy everything AFTER "Bearer "

RUN
---
  export TEAMS_TOKEN="eyJ0eXAi..."
  python export_teams.py

  # Optional: set region explicitly (e.g. au, us, eu) to skip auto-detection
  export TEAMS_REGION=au

RESUME
------
Re-run the same command. Already-downloaded chats are skipped automatically.
"""

import base64
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import requests

OUTPUT_DIR = Path("teams_backup")

# Conversation ID suffixes that indicate team channels — skip these
CHANNEL_SUFFIXES = ("@thread.tacv2", "@thread.skype", "@thread.msftunifiedgroup")

# Suffixes we want: 1:1 chats and group chats
CHAT_SUFFIXES = ("@unq.gbl.spaces", "@thread.v2")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(msg: str, indent: int = 0) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {'  ' * indent}{msg}", flush=True)


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------

def decode_token(token: str) -> dict:
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        return json.loads(base64.b64decode(payload))
    except Exception:
        return {}


def load_token() -> str:
    token = os.environ.get("TEAMS_TOKEN", "").strip()
    if not token:
        print(
            "\nNo token found. Set TEAMS_TOKEN before running:\n"
            "\n  export TEAMS_TOKEN=\"eyJ0eXAi...\""
            "\n  python export_teams.py\n"
            "\nSee the script header for step-by-step instructions.\n",
            flush=True,
        )
        sys.exit(1)

    claims = decode_token(token)
    aud = claims.get("aud", "")
    upn = claims.get("upn") or claims.get("unique_name") or claims.get("preferred_username", "unknown")
    exp = claims.get("exp", 0)

    log(f"Token for: {upn}")

    if "graph.microsoft.com" in aud:
        log("ERROR: This is a Graph API token, not a Teams internal API token.")
        log("Filter DevTools by 'chatsvc' (not 'graph.microsoft.com') and copy that token.")
        sys.exit(1)

    if exp:
        mins = int((datetime.utcfromtimestamp(exp) - datetime.utcnow()).total_seconds() / 60)
        if mins < 0:
            log("ERROR: Token has already expired. Grab a fresh one from DevTools.")
            sys.exit(1)
        log(f"Token valid for ~{mins} more minutes")

    return token


# ---------------------------------------------------------------------------
# HTTP with rate-limit handling
# ---------------------------------------------------------------------------

def get(token: str, url: str, params: dict = None, attempt: int = 0) -> requests.Response:
    """GET with automatic retry on 429 (rate limited) and 5xx errors."""
    headers = {"Authorization": f"Bearer {token}"}
    resp = requests.get(url, headers=headers, params=params, timeout=30)

    if resp.status_code == 429:
        retry_after = int(resp.headers.get("Retry-After", 0))
        wait = max(retry_after, 2 ** min(attempt, 5))  # exponential backoff, cap at 32s
        log(f"Rate limited (429). Waiting {wait}s before retry...", indent=2)
        time.sleep(wait)
        return get(token, url, params, attempt + 1)

    if resp.status_code in (500, 502, 503, 504) and attempt < 3:
        wait = 2 ** attempt
        log(f"Server error ({resp.status_code}). Waiting {wait}s before retry...", indent=2)
        time.sleep(wait)
        return get(token, url, params, attempt + 1)

    resp.raise_for_status()
    return resp


# ---------------------------------------------------------------------------
# Teams internal API
# ---------------------------------------------------------------------------

def find_base_url(token: str) -> str:
    regions = ["au", "us", "eu", "uk", "ap", "in", "ca"]

    region_override = os.environ.get("TEAMS_REGION", "").strip()
    if region_override:
        log(f"Using TEAMS_REGION={region_override}")
        return f"https://teams.cloud.microsoft/api/chatsvc/{region_override}/v1"

    log(f"Auto-detecting region from: {regions}")
    for r in regions:
        url = f"https://teams.cloud.microsoft/api/chatsvc/{r}/v1/users/ME/conversations"
        try:
            resp = requests.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params={"pageSize": 1},
                timeout=10,
            )
            if resp.status_code == 200:
                log(f"Region: {r}")
                return f"https://teams.cloud.microsoft/api/chatsvc/{r}/v1"
            if resp.status_code == 401:
                log("Token rejected (401). Grab a fresh token from DevTools.")
                sys.exit(1)
        except requests.ConnectionError:
            pass

    log("Could not auto-detect region.")
    log("Set it manually: export TEAMS_REGION=au  (use the region from the DevTools URL)")
    sys.exit(1)


def fetch_conversations(base: str, token: str) -> list:
    url = f"{base}/users/ME/conversations"
    params = {
        "view": "msnp24Equivalent|supportsMessageProperties",
        "pageSize": 200,
    }
    results = []
    seen_ids = set()
    page = 1

    # Follow forwardLink (newer) first, then backwardLink (older) from the
    # first response — some dormant conversations only appear via backwardLink.
    backward_url = None

    while url:
        print(f"    -> conversations (page {page})...", end=" ", flush=True)
        resp = get(token, url, params)
        data = resp.json()
        batch = data.get("conversations") or data.get("value") or []

        new = [c for c in batch if c.get("id") not in seen_ids]
        seen_ids.update(c.get("id") for c in new)
        results.extend(new)
        print(f"{len(new)} new items (of {len(batch)})", flush=True)

        meta = data.get("_metadata", {})

        # Capture backwardLink from the first page only
        if page == 1 and meta.get("backwardLink"):
            backward_url = meta["backwardLink"]

        next_url = meta.get("forwardLink") or meta.get("nextLink")
        url = next_url if next_url and batch else None
        params = None
        page += 1
        if url:
            time.sleep(0.5)

    # Now walk backward (older / less-active conversations)
    url = backward_url
    while url:
        print(f"    -> conversations (older, page {page})...", end=" ", flush=True)
        resp = get(token, url, params)
        data = resp.json()
        batch = data.get("conversations") or data.get("value") or []

        new = [c for c in batch if c.get("id") not in seen_ids]
        seen_ids.update(c.get("id") for c in new)
        results.extend(new)
        print(f"{len(new)} new items (of {len(batch)})", flush=True)

        meta = data.get("_metadata", {})
        url = meta.get("backwardLink") if new else None
        page += 1
        if url:
            time.sleep(0.5)

    return results


def fetch_messages(base: str, token: str, conv_id: str, name: str = "") -> list:
    url = f"{base}/users/ME/conversations/{quote(conv_id, safe='')}/messages"
    params = {
        "view": "msnp24Equivalent|supportsMessageProperties",
        "pageSize": 200,
        "startTime": 1,
    }
    label = f"'{name}'" if name else conv_id[:16]
    results = []
    page = 1

    while url:
        print(f"    -> messages {label} (page {page})...", end=" ", flush=True)
        resp = get(token, url, params)
        data = resp.json()
        batch = data.get("messages") or []
        results.extend(batch)
        print(f"{len(batch)} items", flush=True)

        meta = data.get("_metadata", {})
        prev_url = meta.get("backwardLink")  # goes further back in history
        url = prev_url if prev_url and batch else None
        params = None
        page += 1
        if url:
            time.sleep(0.5)

    return list(reversed(results))  # oldest first


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def is_chat(conv: dict) -> bool:
    """Return True for 1:1 and group chats; False for team channels."""
    cid = conv.get("id", "")
    if any(cid.endswith(s) for s in CHANNEL_SUFFIXES):
        return False
    if any(cid.endswith(s) for s in CHAT_SUFFIXES):
        return True
    # Unknown suffix — include but log it
    return True


def names_from_messages(messages: list) -> list[str]:
    """Return unique participant names, preferring fromDisplayNameInToken with imdisplayname as fallback."""
    seen = {}
    for msg in messages:
        name = (msg.get("fromDisplayNameInToken") or msg.get("imdisplayname") or "").strip()
        if name and name not in seen:
            seen[name] = True
    return list(seen.keys())


def chat_label(conv: dict, messages: list) -> str:
    """Human-readable name: prefer fromDisplayNameInToken, fall back to topic/members."""
    # Named group chat
    topic = (conv.get("threadProperties") or {}).get("topic", "").strip()
    if topic:
        return topic

    # Names from actual messages (most reliable)
    names = names_from_messages(messages)
    if names:
        label = ", ".join(names[:4])
        if len(names) > 4:
            label += f" +{len(names) - 4} more"
        return label

    # Last resort: member list from conversation metadata
    members = conv.get("members") or []
    fallback = [
        m.get("friendlyName") or m.get("displayName") or ""
        for m in members
        if m.get("friendlyName") or m.get("displayName")
    ]
    if fallback:
        return ", ".join(fallback[:4])

    return conv.get("id", "unknown")[:16]


# ---------------------------------------------------------------------------
# HTML output
# ---------------------------------------------------------------------------

CSS = """
body { font-family: -apple-system, sans-serif; max-width: 860px;
       margin: 40px auto; padding: 0 20px; color: #222; }
h1   { border-bottom: 2px solid #6264a7; padding-bottom: 8px; color: #6264a7; }
.msg { border-bottom: 1px solid #f0f0f0; padding: 10px 0; }
.who { font-weight: 600; margin-right: 10px; }
.when { color: #888; font-size: .8em; }
.body { margin-top: 6px; line-height: 1.6; }
"""

SKIP_TYPES = {
    "ThreadActivity/AddMember", "ThreadActivity/DeleteMember",
    "ThreadActivity/TopicUpdate", "ThreadActivity/MemberJoined",
    "Event/Call",
}


def render_message(msg: dict) -> str:
    mtype = msg.get("messagetype", "")
    if mtype in SKIP_TYPES:
        return ""
    if mtype and not mtype.startswith("RichText") and mtype not in ("Text", "text", ""):
        return ""

    sender = msg.get("imdisplayname") or msg.get("from") or "Unknown"
    if ":" in sender and not " " in sender:
        sender = sender.split(":")[-1]

    ts = msg.get("originalarrivaltime") or msg.get("composetime") or ""
    content = msg.get("content") or ""

    return (
        f'<div class="msg">'
        f'<span class="who">{sender}</span>'
        f'<span class="when">{ts}</span>'
        f'<div class="body">{content}</div>'
        f'</div>'
    )


def write_html(title: str, messages: list, path: Path) -> None:
    rows = [r for r in (render_message(m) for m in messages) if r]
    content = "".join(rows) if rows else "<p><em>No messages found.</em></p>"
    path.write_text(
        f'<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        f'  <meta charset="utf-8">\n  <title>{title}</title>\n'
        f'  <style>{CSS}</style>\n</head>\n<body>\n'
        f'  <h1>{title}</h1>\n  {content}\n</body>\n</html>',
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Save / resume
# ---------------------------------------------------------------------------

def safe_name(text: str, max_len: int = 80) -> str:
    return re.sub(r'[^\w\s\-]', '_', text).strip()[:max_len]


def build_resume_map(output_dir: Path) -> dict[str, Path]:
    """
    Scan existing download folders and return {conv_id: folder_path}.
    This lets us resume correctly even if folder names change between runs.
    """
    mapping = {}
    for messages_file in output_dir.glob("*/messages.json"):
        try:
            data = json.loads(messages_file.read_text(encoding="utf-8"))
            conv_id = (data.get("conversation") or {}).get("id")
            if conv_id:
                mapping[conv_id] = messages_file.parent
        except Exception:
            pass
    return mapping


def save_chat(dest: Path, label: str, conv: dict, messages: list) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "messages.json").write_text(
        json.dumps({"conversation": conv, "messages": messages}, indent=2, default=str),
        encoding="utf-8",
    )
    write_html(label, messages, dest / "index.html")
    return sum(1 for m in messages if render_message(m))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def rename_existing_folders(output_dir: Path) -> None:
    """
    Re-derive folder names from saved messages.json files and rename if changed.
    Run with: TEAMS_RENAME=1 python export_teams.py
    """
    folders = sorted(output_dir.glob("*/messages.json"))
    if not folders:
        log("No downloaded chats found in output directory.")
        return

    log(f"Checking {len(folders)} folder(s) for better names...")
    renamed = 0

    for messages_file in folders:
        folder = messages_file.parent
        try:
            data = json.loads(messages_file.read_text(encoding="utf-8"))
            conv = data.get("conversation") or {}
            messages = data.get("messages") or []
            conv_id = conv.get("id", "")

            new_label = chat_label(conv, messages)
            suffix = conv_id[-12:] if conv_id else folder.name[-12:]
            new_name = safe_name(f"{new_label}_{suffix}")
            new_folder = output_dir / new_name

            if new_folder == folder:
                log(f"  unchanged: {folder.name}")
                continue

            if new_folder.exists():
                log(f"  skip (target exists): {folder.name} -> {new_name}")
                continue

            folder.rename(new_folder)
            log(f"  renamed: {folder.name}")
            log(f"       ->  {new_name}", indent=1)
            renamed += 1

        except Exception as e:
            log(f"  error processing {folder.name}: {e}")

    log(f"Done — {renamed} folder(s) renamed.")


def conv_id_from_url(url: str) -> str:
    """Extract and URL-decode the conversation ID from a Teams messages URL."""
    from urllib.parse import unquote, urlparse
    # .../conversations/{id}/messages  ->  id
    parts = urlparse(url).path.split("/conversations/")
    if len(parts) < 2:
        raise ValueError(f"Cannot parse conversation ID from URL: {url}")
    return unquote(parts[1].split("/")[0])


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    log(f"Output: {OUTPUT_DIR.resolve()}")

    # Rename mode — no token or API calls needed
    if os.environ.get("TEAMS_RENAME", "").strip() == "1":
        rename_existing_folders(OUTPUT_DIR)
        return

    token = load_token()
    base = find_base_url(token)
    log(f"API base: {base}")

    # Single-conversation mode: set TEAMS_CONV_URL to a messages URL to download
    # just that one chat without fetching the full conversation list.
    single_url = os.environ.get("TEAMS_CONV_URL", "").strip()
    if single_url:
        conv_id = conv_id_from_url(single_url)
        log(f"Single-conversation mode: {conv_id}")
        resume_map = build_resume_map(OUTPUT_DIR)
        if conv_id in resume_map:
            log(f"Already downloaded at '{resume_map[conv_id].name}' — delete that folder to re-download")
            return
        messages = fetch_messages(base, token, conv_id)
        name = chat_label({}, messages)
        folder = OUTPUT_DIR / safe_name(f"{name}_{conv_id[-12:]}")
        log(f"Chat: {name}")
        count = save_chat(folder, name, {}, messages)
        log(f"Saved {count} visible messages -> {folder.name}")
        return

    print(flush=True)
    log("=" * 55)
    log("FETCHING CONVERSATION LIST")
    log("=" * 55)

    all_convs = fetch_conversations(base, token)

    chats = [c for c in all_convs if is_chat(c)]
    skipped_channels = len(all_convs) - len(chats)
    log(f"Total threads: {len(all_convs)}  |  Chats: {len(chats)}  |  Channels skipped: {skipped_channels}")

    resume_map = build_resume_map(OUTPUT_DIR)
    log(f"Found {len(resume_map)} already-downloaded chat(s) to skip")

    summary = []
    resumed = 0

    print(flush=True)
    log("=" * 55)
    log("DOWNLOADING CHATS")
    log("=" * 55)

    for i, conv in enumerate(chats, 1):
        conv_id = conv["id"]

        log(f"[{i}/{len(chats)}] conv: {conv_id[-24:]}")

        if conv_id in resume_map:
            folder = resume_map[conv_id]
            log(f"Already downloaded — skipping '{folder.name}'", indent=1)
            resumed += 1
            summary.append({"name": folder.name, "status": "skipped (already downloaded)"})
            continue

        try:
            messages = fetch_messages(base, token, conv_id)
            name = chat_label(conv, messages)
            folder = OUTPUT_DIR / safe_name(f"{name}_{conv_id[-12:]}")
            log(f"Chat: {name}", indent=1)
            log(f"Fetched {len(messages)} messages, saving...", indent=1)
            count = save_chat(folder, name, conv, messages)
            log(f"Saved {count} visible messages -> {folder.name}", indent=1)
            summary.append({"name": name, "messages": count})
        except requests.HTTPError as e:
            log(f"ERROR: {e}", indent=1)
            summary.append({"name": conv_id[-24:], "error": str(e)})

        time.sleep(0.5)

    (OUTPUT_DIR / "_index.json").write_text(
        json.dumps({"exported_at": datetime.utcnow().isoformat(), "chats": summary}, indent=2),
        encoding="utf-8",
    )

    ok = sum(1 for s in summary if "error" not in s and "skipped" not in s.get("status", ""))
    print(flush=True)
    log("=" * 55)
    log(f"DONE — {ok} downloaded, {resumed} skipped (already done), "
        f"{sum(1 for s in summary if 'error' in s)} errors")
    log(f"Output: {OUTPUT_DIR.resolve()}")
    log("=" * 55)


if __name__ == "__main__":
    main()
