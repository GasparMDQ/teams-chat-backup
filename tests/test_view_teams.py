import json
import pytest
from pathlib import Path
from view_teams import strip_html, load_chats, detect_self, folder_display_name, generate_viewer


def test_strip_html_removes_tags():
    assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"


def test_strip_html_handles_entities():
    assert strip_html("<p>A &amp; B</p>") == "A & B"


def test_strip_html_empty():
    assert strip_html("") == ""


def test_load_chats_reads_messages(tmp_path):
    conv_dir = tmp_path / "Alice Smith_abc123thread_v2"
    conv_dir.mkdir()
    data = {
        "conversation": {"id": "19:abc@thread.v2"},
        "messages": [
            {
                "messagetype": "RichText/Html",
                "imdisplayname": "Alice Smith",
                "composetime": "2024-01-15T09:00:00.000Z",
                "content": "<p>Hello!</p>",
            },
            {
                "messagetype": "ThreadActivity/AddMember",
                "imdisplayname": "system",
                "composetime": "2024-01-15T08:00:00.000Z",
                "content": "<addmember/>",
            },
        ],
    }
    (conv_dir / "messages.json").write_text(json.dumps(data))

    chats = load_chats(tmp_path)

    assert len(chats) == 1
    chat = chats[0]
    assert chat["name"] == "Alice Smith_abc123thread_v2"
    assert chat["message_count"] == 1
    assert chat["messages"][0]["sender"] == "Alice Smith"
    assert chat["messages"][0]["html"] == "<p>Hello!</p>"
    assert chat["messages"][0]["text"] == "Hello!"
    assert chat["messages"][0]["time"] == "2024-01-15T09:00:00.000Z"


def test_load_chats_skips_folders_without_messages_json(tmp_path):
    (tmp_path / "empty_folder").mkdir()
    assert load_chats(tmp_path) == []


def test_load_chats_sorts_by_message_count(tmp_path):
    for name, count in [("Chat_A_id1", 1), ("Chat_B_id2", 5), ("Chat_C_id3", 3)]:
        d = tmp_path / name
        d.mkdir()
        msgs = [
            {
                "messagetype": "RichText/Html",
                "imdisplayname": "X",
                "composetime": "2024-01-01T00:00:00.000Z",
                "content": "<p>msg</p>",
            }
            for _ in range(count)
        ]
        (d / "messages.json").write_text(json.dumps({"conversation": {"id": "19:x"}, "messages": msgs}))

    chats = load_chats(tmp_path)
    assert [c["message_count"] for c in chats] == [5, 3, 1]


def test_load_chats_since_is_earliest_message(tmp_path):
    d = tmp_path / "Chat_id1"
    d.mkdir()
    msgs = [
        {"messagetype": "RichText/Html", "imdisplayname": "X",
         "composetime": "2024-06-01T00:00:00.000Z", "content": "<p>b</p>"},
        {"messagetype": "RichText/Html", "imdisplayname": "X",
         "composetime": "2023-01-15T00:00:00.000Z", "content": "<p>a</p>"},
    ]
    (d / "messages.json").write_text(json.dumps({"conversation": {"id": "19:x"}, "messages": msgs}))
    chats = load_chats(tmp_path)
    assert chats[0]["since"] == "2023-01-15"


def test_detect_self_returns_most_common_sender(tmp_path):
    chats = [
        {"messages": [{"sender": "Me"}, {"sender": "Alice"}]},
        {"messages": [{"sender": "Me"}, {"sender": "Bob"}]},
        {"messages": [{"sender": "Me"}]},
    ]
    assert detect_self(chats) == "Me"


def test_detect_self_empty():
    assert detect_self([]) is None


def test_folder_display_name_strips_gbl_spaces():
    assert folder_display_name("Alice Smith_q_gbl_spaces") == "Alice Smith"


def test_folder_display_name_strips_thread_v2():
    assert folder_display_name("Project Team_81_thread_v2") == "Project Team"


def test_folder_display_name_leaves_unrecognised_unchanged():
    assert folder_display_name("some_folder_name") == "some_folder_name"


def test_generate_viewer_creates_file(tmp_path):
    backup = tmp_path / "backup"
    backup.mkdir()
    d = backup / "Alice_q_gbl_spaces"
    d.mkdir()
    msgs = [{"messagetype": "RichText/Html", "imdisplayname": "Alice",
              "composetime": "2024-01-01T10:00:00.000Z", "content": "<p>Hi</p>"}]
    (d / "messages.json").write_text(
        json.dumps({"conversation": {"id": "19:x"}, "messages": msgs})
    )
    out = tmp_path / "viewer.html"
    generate_viewer(backup, out)
    assert out.exists()


def test_generate_viewer_embeds_sender_name(tmp_path):
    backup = tmp_path / "backup"
    backup.mkdir()
    d = backup / "Alice_q_gbl_spaces"
    d.mkdir()
    msgs = [{"messagetype": "RichText/Html", "imdisplayname": "Alice",
              "composetime": "2024-01-01T10:00:00.000Z", "content": "<p>Hi</p>"}]
    (d / "messages.json").write_text(
        json.dumps({"conversation": {"id": "19:x"}, "messages": msgs})
    )
    out = tmp_path / "viewer.html"
    generate_viewer(backup, out)
    content = out.read_text()
    # load_chats maps imdisplayname -> sender; check key+value in serialised JSON
    assert '"sender": "Alice"' in content
    # load_chats maps content -> html; check raw HTML value in JSON
    assert '"html": "<p>Hi</p>"' in content
    # load_chats strips HTML for the text field used by search
    assert '"text": "Hi"' in content


def test_generate_viewer_is_valid_html(tmp_path):
    backup = tmp_path / "backup"
    backup.mkdir()
    out = tmp_path / "viewer.html"
    generate_viewer(backup, out)
    content = out.read_text()
    assert content.startswith("<!DOCTYPE html>")
    assert "</html>" in content


def test_generate_viewer_contains_app_scaffold(tmp_path):
    backup = tmp_path / "backup"
    backup.mkdir()
    out = tmp_path / "viewer.html"
    generate_viewer(backup, out)
    content = out.read_text()
    assert 'id="app"' in content
    assert 'id="sidebar"' in content
    assert 'id="messages"' in content
    assert 'id="search"' in content
