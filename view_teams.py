import json
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


def load_chats(backup_dir: Path) -> list:
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
            "name": folder.name,
            "message_count": len(messages),
            "since": since,
            "messages": messages,
        })

    chats.sort(key=lambda c: c["message_count"], reverse=True)
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
