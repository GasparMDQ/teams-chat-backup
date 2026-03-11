from pathlib import Path


def strip_html(s: str) -> str:
    raise NotImplementedError


def load_chats(backup_dir: Path) -> list:
    raise NotImplementedError


def detect_self(chats: list) -> str | None:
    raise NotImplementedError
