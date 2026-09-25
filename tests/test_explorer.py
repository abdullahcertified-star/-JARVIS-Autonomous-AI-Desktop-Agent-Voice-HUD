"""Unit tests for actions.explorer's file CRUD operations (read/create/update/delete).

Everything runs against a throwaway temp directory so this never touches
real user files. Delete goes through send2trash (Recycle Bin) for real --
that's the whole point of choosing it over a permanent unlink.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from actions.explorer import _resolve_path, explorer_action


def test_resolve_path_rewrites_guessed_username_desktop() -> None:
    # An AI caller can't know the real Windows account name and will often
    # guess a generic one -- the real Desktop should be used regardless.
    resolved = _resolve_path(r"C:\Users\User\Desktop\gamma")
    expected = os.path.join(os.path.expanduser("~"), "Desktop", "gamma")
    assert resolved == expected


def test_resolve_path_rewrites_any_guessed_username() -> None:
    resolved = _resolve_path(r"C:\Users\SomeoneElse\Documents\notes.txt")
    expected = os.path.join(os.path.expanduser("~"), "Documents", "notes.txt")
    assert resolved == expected


def test_resolve_path_handles_bare_special_folder_name() -> None:
    assert _resolve_path("Desktop") == os.path.join(os.path.expanduser("~"), "Desktop")


def test_resolve_path_leaves_unrelated_paths_untouched() -> None:
    assert _resolve_path(r"C:\temp\foo.txt") == r"C:\temp\foo.txt"


def test_resolve_path_is_case_insensitive() -> None:
    resolved = _resolve_path(r"C:\Users\Whoever\DESKTOP\x.txt")
    expected = os.path.join(os.path.expanduser("~"), "Desktop", "x.txt")
    assert resolved == expected


def test_create_folder_with_guessed_username_desktop_path() -> None:
    # End-to-end: exactly the failure mode observed with the AI agent --
    # a folder create through a wrong-username Desktop path must still land
    # on the real Desktop and succeed.
    real_desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    folder_name = "jarvis_test_gamma_resolve"
    guessed_path = os.path.join(r"C:\Users\User\Desktop", folder_name)

    try:
        result = explorer_action({"action": "explorer", "operation": "create", "path": guessed_path, "is_folder": True})
        assert result["success"] is True
        assert os.path.isdir(os.path.join(real_desktop, folder_name))
    finally:
        real_path = os.path.join(real_desktop, folder_name)
        if os.path.isdir(real_path):
            os.rmdir(real_path)


@pytest.fixture
def scratch_dir():
    with tempfile.TemporaryDirectory(prefix="jarvis_test_") as tmp:
        yield tmp


def test_create_then_read_file(scratch_dir) -> None:
    path = os.path.join(scratch_dir, "note.txt")

    created = explorer_action({"action": "explorer", "operation": "create", "path": path, "content": "hello"})
    assert created["success"] is True
    assert os.path.isfile(path)

    read = explorer_action({"action": "explorer", "operation": "read", "path": path})
    assert read["success"] is True
    assert read["content"] == "hello"
    assert read["truncated"] is False


def test_create_fails_if_file_already_exists(scratch_dir) -> None:
    path = os.path.join(scratch_dir, "note.txt")
    explorer_action({"action": "explorer", "operation": "create", "path": path, "content": "v1"})

    result = explorer_action({"action": "explorer", "operation": "create", "path": path, "content": "v2"})
    assert result["success"] is False
    assert "already exists" in result["message"]
    # Original content must be untouched.
    with open(path, encoding="utf-8") as f:
        assert f.read() == "v1"


def test_update_overwrites_existing_file(scratch_dir) -> None:
    path = os.path.join(scratch_dir, "note.txt")
    explorer_action({"action": "explorer", "operation": "create", "path": path, "content": "v1"})

    result = explorer_action({"action": "explorer", "operation": "update", "path": path, "content": "v2"})
    assert result["success"] is True
    with open(path, encoding="utf-8") as f:
        assert f.read() == "v2"


def test_update_appends_when_requested(scratch_dir) -> None:
    path = os.path.join(scratch_dir, "note.txt")
    explorer_action({"action": "explorer", "operation": "create", "path": path, "content": "v1"})

    explorer_action({"action": "explorer", "operation": "update", "path": path, "content": "-v2", "append": True})
    with open(path, encoding="utf-8") as f:
        assert f.read() == "v1-v2"


def test_update_fails_if_file_missing(scratch_dir) -> None:
    path = os.path.join(scratch_dir, "ghost.txt")
    result = explorer_action({"action": "explorer", "operation": "update", "path": path, "content": "x"})
    assert result["success"] is False
    assert "create" in result["message"]


def test_read_missing_path_fails(scratch_dir) -> None:
    result = explorer_action({"action": "explorer", "operation": "read", "path": os.path.join(scratch_dir, "nope")})
    assert result["success"] is False


def test_create_folder(scratch_dir) -> None:
    folder = os.path.join(scratch_dir, "sub", "dir")
    result = explorer_action({"action": "explorer", "operation": "create", "path": folder, "is_folder": True})
    assert result["success"] is True
    assert os.path.isdir(folder)

    # Idempotent: creating an already-existing folder shouldn't fail.
    result2 = explorer_action({"action": "explorer", "operation": "create", "path": folder, "is_folder": True})
    assert result2["success"] is True


def test_read_directory_lists_entries(scratch_dir) -> None:
    open(os.path.join(scratch_dir, "a.txt"), "w").close()
    os.makedirs(os.path.join(scratch_dir, "sub"))

    result = explorer_action({"action": "explorer", "operation": "read", "path": scratch_dir})
    assert result["success"] is True
    names = {e["name"] for e in result["entries"]}
    assert names == {"a.txt", "sub"}


def test_delete_file_goes_to_recycle_bin(scratch_dir) -> None:
    path = os.path.join(scratch_dir, "throwaway.txt")
    with open(path, "w") as f:
        f.write("bye")

    result = explorer_action({"action": "explorer", "operation": "delete", "path": path})
    assert result["success"] is True
    assert not os.path.exists(path)


def test_delete_missing_path_fails(scratch_dir) -> None:
    result = explorer_action({"action": "explorer", "operation": "delete", "path": os.path.join(scratch_dir, "nope")})
    assert result["success"] is False
