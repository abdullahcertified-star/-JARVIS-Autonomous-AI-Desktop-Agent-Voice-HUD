"""Tests for actions/macro.py and agent macro workflow automation."""

from unittest.mock import MagicMock, patch
import pytest

from dispatcher import dispatch
from actions import macro
import agent


def test_list_workflows_contains_defaults():
    res = dispatch({
        "action": "macro",
        "operation": "list",
    })
    assert res["success"] is True
    assert "dev_workspace" in res["message"]
    assert "goodnight_routine" in res["message"]
    assert "workflows" in res
    assert "dev_workspace" in res["workflows"]


def test_save_and_delete_custom_workflow(tmp_path, monkeypatch):
    test_json = tmp_path / "test_workflows.json"
    monkeypatch.setattr(macro.config, "WORKFLOWS_JSON_PATH", test_json)

    # 1. Save new workflow
    steps = [
        {"action": "open_app", "target": "notepad"},
        {"action": "system", "operation": "set_volume", "level": 25},
    ]
    save_res = dispatch({
        "action": "macro",
        "operation": "save",
        "name": "study_session",
        "description": "Open Notepad and set volume to 25%",
        "steps": steps,
    })
    assert save_res["success"] is True
    assert "study_session" in save_res["message"]

    # 2. Check it appears in listing
    list_res = dispatch({"action": "macro", "operation": "list"})
    assert list_res["success"] is True
    assert "study_session" in list_res["workflows"]
    assert list_res["workflows"]["study_session"]["description"] == "Open Notepad and set volume to 25%"

    # 3. Delete it
    del_res = dispatch({
        "action": "macro",
        "operation": "delete",
        "name": "study_session",
    })
    assert del_res["success"] is True

    # 4. Check it is gone
    list_after = dispatch({"action": "macro", "operation": "list"})
    assert "study_session" not in list_after["workflows"]


def test_save_workflow_validations():
    # Missing name
    res1 = dispatch({"action": "macro", "operation": "save", "steps": []})
    assert res1["success"] is False
    assert "name" in res1["message"]

    # Empty steps
    res2 = dispatch({"action": "macro", "operation": "save", "name": "bad", "steps": []})
    assert res2["success"] is False
    assert "steps" in res2["message"]


def test_run_workflow_execution():
    call_log = []

    def mock_dispatch(payload):
        call_log.append(payload)
        return {"success": True, "message": f"{payload.get('action')} done"}

    with patch("dispatcher.dispatch", side_effect=mock_dispatch):
        res = macro.run_workflow_by_name("dev_workspace")
        assert res["success"] is True
        assert "dev_workspace" in res["message"]
        assert res["steps_total"] == 4
        assert res["steps_succeeded"] == 4
        assert len(call_log) == 4
        assert call_log[0]["action"] == "open_app"


def test_run_unknown_workflow():
    res = dispatch({
        "action": "macro",
        "operation": "run",
        "name": "non_existent_super_macro_xyz",
    })
    assert res["success"] is False
    assert "not found" in res["message"]


def test_agent_workflow_tools():
    with patch("agent.dispatch") as mock_dispatch:
        mock_dispatch.return_value = {"success": True, "message": "Workflow dev_workspace completed"}
        res = agent.run_workflow("dev_workspace")
        assert "Workflow dev_workspace completed" in res

        mock_dispatch.return_value = {"success": True, "message": "Configured workflows listed"}
        res2 = agent.list_workflows()
        assert "Configured workflows listed" in res2

        mock_dispatch.return_value = {"success": True, "message": "Saved"}
        res3 = agent.create_custom_workflow("focus", [{"action": "open_app", "target": "code"}])
        assert "Saved" in res3


def test_fast_path_workflows():
    with patch("agent.run_workflow", return_value="Sir, workspace is ready.") as mock_run, \
         patch("agent.list_workflows", return_value="Sir, here are your workflows.") as mock_list:

        res1 = agent.check_fast_path("Jarvis, prepare dev workspace")
        assert res1 == "Sir, workspace is ready."
        mock_run.assert_called_with("dev_workspace")

        res2 = agent.check_fast_path("goodnight routine")
        assert res2 == "Sir, workspace is ready."
        mock_run.assert_called_with("goodnight_routine")

        res3 = agent.check_fast_path("meeting mode")
        assert res3 == "Sir, workspace is ready."
        mock_run.assert_called_with("meeting_mode")

        res4 = agent.check_fast_path("list all workflows")
        assert res4 == "Sir, here are your workflows."
        mock_list.assert_called_once()
