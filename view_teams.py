import json
import re
import datetime
import argparse
import webbrowser
import sys
from pathlib import Path
from html.parser import HTMLParser
from collections import Counter


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self._parts.append(data)

    def handle_entityref(self, name: str) -> None:
        import html
        self._parts.append(html.unescape(f"&{name};"))

    def handle_charref(self, name: str) -> None:
        import html
        self._parts.append(html.unescape(f"&#{name};"))


def strip_html(s: str) -> str:
    if not s:
        return ""
    p = _TextExtractor()
    p.feed(s)
    return "".join(p._parts).strip()


def folder_display_name(folder_name: str) -> str:
    """Strip the _<id_fragment> suffix appended by export_teams.py."""
    return re.sub(
        r'_[a-z0-9]{1,3}_(?:gbl_spaces|thread_v[23]|thread_tacv2)$',
        '',
        folder_name,
        flags=re.IGNORECASE,
    )


def chat_display_name(raw_name: str, user_name: str = "") -> str:
    """Convert a folder-derived name to a human-readable chat title.

    - Replaces underscore separators with ', '
    - Optionally removes the user's own name from the participant list
    """
    name = re.sub(r'\s*_\s*', ', ', raw_name)
    if user_name:
        parts = [p.strip() for p in name.split(", ") if p.strip()]
        filtered = [p for p in parts if p.lower() != user_name.strip().lower()]
        if filtered:
            name = ", ".join(filtered)
    return name.strip(", ").strip()


def load_chats(backup_dir: Path, user_name: str = "") -> list:
    chats = []
    backup_dir = Path(backup_dir)
    for messages_file in sorted(backup_dir.glob("*/messages.json")):
        folder = messages_file.parent
        try:
            data = json.loads(messages_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        raw_msgs = data.get("messages", [])
        messages = []
        for m in raw_msgs:
            if m.get("messagetype") != "RichText/Html":
                continue
            messages.append({
                "sender": m.get("imdisplayname", ""),
                "time": m.get("composetime", ""),
                "html": m.get("content", ""),
                "text": strip_html(m.get("content", "")),
            })

        since = ""
        times = [m["time"] for m in messages if m["time"]]
        if times:
            since = min(times)[:10]

        chats.append({
            "id": folder.name,
            "name": chat_display_name(folder_display_name(folder.name), user_name),
            "message_count": len(messages),
            "since": since,
            "messages": messages,
        })

    chats.sort(key=lambda c: c["name"].lower())
    return chats


def detect_self(chats: list) -> str | None:
    if not chats:
        return None
    # The user appears in every conversation — find the name present in most chats
    presence: Counter = Counter()
    for chat in chats:
        senders_in_chat = {m["sender"] for m in chat["messages"]}
        for s in senders_in_chat:
            presence[s] += 1
    if not presence:
        return None
    return presence.most_common(1)[0][0]


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Teams Viewer</title>
  <style>
    :root {
      --bg: #f3f4f6;
      --surface: #ffffff;
      --border: #e5e7eb;
      --text: #111827;
      --muted: #6b7280;
      --accent: #6d28d9;
      --acc-bg: #ede9fe;
      --acc-bd: #c4b5fd;
      --bubble-bg: #f9fafb;
      --bubble-bd: #e5e7eb;
      --sidebar-bg: #ffffff;
      --header-bg: #6d28d9;
      --input-bg: #ffffff;
      --mark-bg: #fde68a;
    }
    body.dark {
      --bg: #0f172a;
      --surface: #1e293b;
      --border: #334155;
      --text: #f1f5f9;
      --muted: #94a3b8;
      --accent: #a78bfa;
      --acc-bg: #2e1065;
      --acc-bd: #7c3aed;
      --bubble-bg: #1e293b;
      --bubble-bd: #334155;
      --sidebar-bg: #1e293b;
      --header-bg: #1e1b4b;
      --input-bg: #0f172a;
      --mark-bg: #92400e;
    }
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      font-size: 14px;
    }
    #app {
      display: flex;
      flex-direction: column;
      height: 100vh;
      overflow: hidden;
    }
    #topbar {
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 8px 16px;
      background: var(--header-bg);
      color: #fff;
      flex-shrink: 0;
      min-height: 48px;
    }
    #brand {
      font-weight: 700;
      font-size: 16px;
      white-space: nowrap;
      color: #fff;
    }
    #search {
      flex: 1;
      padding: 6px 12px;
      border: none;
      border-radius: 20px;
      background: var(--input-bg);
      color: var(--text);
      font-size: 14px;
      outline: none;
      max-width: 500px;
    }
    #search:focus { box-shadow: 0 0 0 2px var(--acc-bd); }
    #stats {
      font-size: 12px;
      color: rgba(255,255,255,0.75);
      white-space: nowrap;
    }
    #theme-btn {
      background: rgba(255,255,255,0.15);
      border: none;
      color: #fff;
      padding: 4px 10px;
      border-radius: 14px;
      cursor: pointer;
      font-size: 13px;
      white-space: nowrap;
    }
    #theme-btn:hover { background: rgba(255,255,255,0.25); }
    #body {
      display: flex;
      flex: 1;
      overflow: hidden;
    }
    #sidebar {
      width: 220px;
      flex-shrink: 0;
      background: var(--sidebar-bg);
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }
    #sidebar-label {
      padding: 10px 14px 6px;
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--muted);
    }
    #chat-list {
      overflow-y: auto;
      flex: 1;
    }
    .chat-item {
      padding: 8px 14px;
      cursor: pointer;
      border-left: 3px solid transparent;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 6px;
    }
    .chat-item:hover { background: var(--acc-bg); }
    .chat-item.active {
      background: var(--acc-bg);
      border-left-color: var(--accent);
    }
    .chat-name {
      flex: 1;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      font-size: 13px;
    }
    .chat-badge {
      background: var(--accent);
      color: #fff;
      border-radius: 10px;
      padding: 1px 7px;
      font-size: 11px;
      flex-shrink: 0;
    }
    #pane {
      flex: 1;
      display: flex;
      flex-direction: column;
      overflow: hidden;
      background: var(--surface);
    }
    #pane-header {
      padding: 12px 16px;
      border-bottom: 1px solid var(--border);
      flex-shrink: 0;
    }
    #pane-title {
      font-weight: 600;
      font-size: 15px;
    }
    #pane-subtitle {
      font-size: 12px;
      color: var(--muted);
      margin-top: 2px;
    }
    #messages {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }
    #search-results {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
    }
    .msg-group {
      display: flex;
      flex-direction: column;
      gap: 2px;
      max-width: 75%;
    }
    .msg-group.self { align-items: flex-end; align-self: flex-end; }
    .msg-meta {
      font-size: 11px;
      color: var(--muted);
      padding: 0 4px;
    }
    .msg-bubble {
      background: var(--bubble-bg);
      border: 1px solid var(--bubble-bd);
      border-radius: 12px;
      padding: 8px 12px;
      line-height: 1.5;
      word-break: break-word;
    }
    .msg-bubble.self {
      background: var(--acc-bg);
      border-color: var(--acc-bd);
    }
    .msg-bubble p { margin: 0 0 4px; }
    .msg-bubble p:last-child { margin-bottom: 0; }
    .msg-bubble a { color: var(--accent); }
    .res-group-title {
      font-weight: 600;
      font-size: 13px;
      margin: 16px 0 6px;
      color: var(--accent);
    }
    .res-group-title:first-child { margin-top: 0; }
    .res-item {
      padding: 8px 12px;
      border: 1px solid var(--border);
      border-radius: 8px;
      margin-bottom: 6px;
      cursor: pointer;
      background: var(--bubble-bg);
    }
    .res-item:hover { border-color: var(--accent); }
    .res-meta {
      font-size: 11px;
      color: var(--muted);
      margin-bottom: 4px;
    }
    .res-snippet { font-size: 13px; line-height: 1.4; }
    .no-results { color: var(--muted); text-align: center; padding: 40px 0; }
    mark { background: var(--mark-bg); border-radius: 2px; padding: 0 1px; }
    .msg-group.msg-highlighted > .msg-bubble {
      outline: 2px solid var(--accent);
      outline-offset: 2px;
    }
  </style>
</head>
<body>
<div id="app">
  <div id="topbar">
    <span id="brand">Teams Viewer</span>
    <input id="search" type="search" placeholder="Search chats and messages\u2026" autocomplete="off">
    <span id="stats"></span>
    <button id="theme-btn" onclick="toggleTheme()">&#x1F319; Dark</button>
  </div>
  <div id="body">
    <div id="sidebar">
      <div id="sidebar-label">Conversations</div>
      <div id="chat-list"></div>
    </div>
    <div id="pane">
      <div id="pane-header">
        <div id="pane-title">Select a conversation</div>
        <div id="pane-subtitle"></div>
      </div>
      <div id="messages"></div>
      <div id="search-results" style="display:none"></div>
    </div>
  </div>
</div>
<script>
const DATA = __TEAMS_DATA__;

let activeChatId = null;
let highlightedEl = null;

function fmt(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString();
  } catch(e) {
    return iso;
  }
}

function fmtSince(ymd) {
  if (!ymd) return '';
  try {
    const [y, m] = ymd.split('-');
    return new Date(parseInt(y), parseInt(m) - 1, 1)
      .toLocaleString('default', { month: 'short', year: 'numeric' });
  } catch(e) {
    return ymd;
  }
}

function appendHighlighted(container, text, query) {
  const re = new RegExp('(' + query.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&') + ')', 'gi');
  text.split(re).forEach(part => {
    if (part.toLowerCase() === query.toLowerCase()) {
      const mark = document.createElement('mark');
      mark.textContent = part;
      container.appendChild(mark);
    } else {
      container.appendChild(document.createTextNode(part));
    }
  });
}

function renderSidebar(query) {
  const list = document.getElementById('chat-list');
  list.textContent = '';
  const q = query.trim().toLowerCase();
  DATA.chats.forEach(chat => {
    let matchCount = 0;
    if (q) {
      const nameMatch = chat.name.toLowerCase().includes(q);
      const msgMatches = chat.messages.filter(m => m.text.toLowerCase().includes(q)).length;
      matchCount = nameMatch ? chat.message_count : msgMatches;
      if (matchCount === 0) return;
    }

    const item = document.createElement('div');
    item.className = 'chat-item' + (chat.id === activeChatId ? ' active' : '');
    item.addEventListener('click', () => openChat(chat.id));

    const nameSpan = document.createElement('span');
    nameSpan.className = 'chat-name';
    nameSpan.textContent = chat.name;
    item.appendChild(nameSpan);

    if (q && matchCount > 0) {
      const badge = document.createElement('span');
      badge.className = 'chat-badge';
      badge.textContent = matchCount;
      item.appendChild(badge);
    }

    list.appendChild(item);
  });
}

function openChat(id) {
  activeChatId = id;
  if (highlightedEl) {
    highlightedEl.classList.remove('msg-highlighted');
    highlightedEl = null;
  }
  document.getElementById('search').value = '';
  renderSidebar('');

  const chat = DATA.chats.find(c => c.id === id);
  if (!chat) return;

  document.getElementById('pane-title').textContent = chat.name;
  const sub = chat.since
    ? chat.message_count + ' messages \u00b7 since ' + fmtSince(chat.since)
    : chat.message_count + ' messages';
  document.getElementById('pane-subtitle').textContent = sub;

  document.getElementById('search-results').style.display = 'none';
  const msgDiv = document.getElementById('messages');
  msgDiv.style.display = '';
  msgDiv.textContent = '';

  chat.messages.forEach(m => {
    const group = document.createElement('div');
    group.className = 'msg-group' + (m.sender === DATA.self ? ' self' : '');
    group.dataset.msgTime = m.time;

    const meta = document.createElement('div');
    meta.className = 'msg-meta';
    meta.textContent = m.sender + ' \u00b7 ' + fmt(m.time);
    group.appendChild(meta);

    const bubble = document.createElement('div');
    bubble.className = 'msg-bubble' + (m.sender === DATA.self ? ' self' : '');

    const parser = new DOMParser();
    const doc = parser.parseFromString(m.html, 'text/html');
    Array.from(doc.body.childNodes).forEach(n => bubble.appendChild(n.cloneNode(true)));

    group.appendChild(bubble);
    msgDiv.appendChild(group);
  });

  msgDiv.scrollTop = msgDiv.scrollHeight;
}

function scrollToMessage(time) {
  if (highlightedEl) {
    highlightedEl.classList.remove('msg-highlighted');
    highlightedEl = null;
  }
  const groups = document.querySelectorAll('.msg-group');
  for (const el of groups) {
    if (el.dataset.msgTime === time) {
      el.scrollIntoView({ behavior: 'smooth', block: 'center' });
      el.classList.add('msg-highlighted');
      highlightedEl = el;
      break;
    }
  }
}

function doSearch(query) {
  const q = query.trim();
  if (!q) {
    document.getElementById('search-results').style.display = 'none';
    document.getElementById('messages').style.display = '';
    renderSidebar('');
    document.getElementById('pane-title').textContent = activeChatId
      ? (DATA.chats.find(c => c.id === activeChatId) || {}).name || 'Select a conversation'
      : 'Select a conversation';
    document.getElementById('pane-subtitle').textContent = '';
    return;
  }

  const ql = q.toLowerCase();
  renderSidebar(q);

  document.getElementById('messages').style.display = 'none';
  const resultsDiv = document.getElementById('search-results');
  resultsDiv.style.display = '';
  resultsDiv.textContent = '';

  document.getElementById('pane-title').textContent = 'Search results';
  document.getElementById('pane-subtitle').textContent = '\u201c' + q + '\u201d';

  let totalResults = 0;

  DATA.chats.forEach(chat => {
    const nameMatch = chat.name.toLowerCase().includes(ql);
    const matchingMsgs = chat.messages.filter(m => m.text.toLowerCase().includes(ql));
    if (!nameMatch && matchingMsgs.length === 0) return;

    const groupTitle = document.createElement('div');
    groupTitle.className = 'res-group-title';
    groupTitle.textContent = chat.name;
    resultsDiv.appendChild(groupTitle);

    matchingMsgs.forEach(m => {
      totalResults++;
      const item = document.createElement('div');
      item.className = 'res-item';
      item.addEventListener('click', () => {
        openChat(chat.id);
        setTimeout(() => scrollToMessage(m.time), 50);
      });

      const meta = document.createElement('div');
      meta.className = 'res-meta';
      meta.textContent = m.sender + ' \u00b7 ' + fmt(m.time);
      item.appendChild(meta);

      const snippet = document.createElement('div');
      snippet.className = 'res-snippet';
      appendHighlighted(snippet, m.text.slice(0, 300), q);
      item.appendChild(snippet);

      resultsDiv.appendChild(item);
    });
  });

  if (totalResults === 0 && DATA.chats.every(c => !c.name.toLowerCase().includes(ql))) {
    const noRes = document.createElement('div');
    noRes.className = 'no-results';
    noRes.textContent = 'No results found for \u201c' + q + '\u201d';
    resultsDiv.appendChild(noRes);
  }
}

function toggleTheme() {
  const dark = document.body.classList.toggle('dark');
  document.getElementById('theme-btn').textContent = dark ? '\u2600\ufe0f Light' : '\U0001F319 Dark';
  try { localStorage.setItem('theme', dark ? 'dark' : 'light'); } catch(e) {}
}

// Init
(function() {
  try {
    if (localStorage.getItem('theme') === 'dark') {
      document.body.classList.add('dark');
      document.getElementById('theme-btn').textContent = '\u2600\ufe0f Light';
    }
  } catch(e) {}

  const totalMsgs = DATA.chats.reduce((s, c) => s + c.message_count, 0);
  document.getElementById('stats').textContent =
    DATA.chats.length + ' chats \u00b7 ' + totalMsgs + ' messages';

  document.getElementById('search').addEventListener('input', e => doSearch(e.target.value));

  renderSidebar('');
  if (DATA.chats.length > 0) {
    openChat(DATA.chats[0].id);
  }
})();
</script>
</body>
</html>"""


def generate_viewer(backup_dir: Path, output_path: Path, user_name: str = "") -> None:
    chats = load_chats(Path(backup_dir), user_name)
    self_name = user_name or detect_self(chats)
    payload = {
        "generated_at": datetime.datetime.now().isoformat(),
        "self": self_name or "",
        "chats": chats,
    }
    data_js = json.dumps(payload, ensure_ascii=False)
    html = _TEMPLATE.replace("__TEAMS_DATA__", data_js)
    Path(output_path).write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Browse your Teams chat backup in a browser."
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("teams_backup"),
        help="Path to the teams_backup directory (default: ./teams_backup)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("teams_viewer.html"),
        help="Output HTML file path (default: ./teams_viewer.html)",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Generate the file without opening the browser",
    )
    parser.add_argument(
        "--name",
        default="",
        help="Your display name (e.g. 'Jane Smith') — filters it from chat titles and marks your messages",
    )
    args = parser.parse_args()

    if not args.dir.exists():
        print(f"Error: backup directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Reading chats from {args.dir}...")
    generate_viewer(args.dir, args.output, user_name=args.name)
    print(f"Viewer written to {args.output.resolve()}")

    if not args.no_open:
        webbrowser.open(args.output.resolve().as_uri())


if __name__ == "__main__":
    main()
