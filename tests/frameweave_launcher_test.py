"""统一启动的离线测试：不监听端口、不启动进程、不调用生成服务。"""

import subprocess
from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest

from frameweave import launcher


def response(body):
    """构造支持上下文管理的 HTTP 响应，保持探测逻辑真实执行。"""
    value = MagicMock()
    value.status = 200
    value.read.return_value = body
    value.__enter__.return_value = value
    return value


def test_free_port_does_not_issue_http(monkeypatch):
    monkeypatch.setattr(launcher, "port_is_open", lambda port: False)
    opener = MagicMock()
    monkeypatch.setattr(launcher, "build_opener", opener)
    assert launcher.probe_creator() == "free"
    opener.assert_not_called()


def test_existing_streamlit_requires_health_and_page_identity(monkeypatch):
    monkeypatch.setattr(launcher, "port_is_open", lambda port: True)
    opener = MagicMock()
    monkeypatch.setattr(launcher, "build_opener", lambda handler: opener)
    monkeypatch.setattr(launcher, "creator_process_matches", lambda expected_pid: True)
    opener.open.side_effect = [
        response(b"ok"),
        response(b"<title>Streamlit</title><script>window.prerenderReady = false</script>"),
    ]
    assert launcher.probe_creator() == "streamlit"
    opener.open.side_effect = [response(b"ok"), response(b"<title>Another service</title>")]
    assert launcher.probe_creator() == "occupied"
    opener.open.side_effect = OSError("offline")
    assert launcher.probe_creator() == "occupied"


def test_other_streamlit_repository_is_not_reused(monkeypatch):
    monkeypatch.setattr(launcher, "port_is_open", lambda port: True)
    opener = MagicMock()
    monkeypatch.setattr(launcher, "build_opener", lambda handler: opener)
    monkeypatch.setattr(launcher, "creator_process_matches", lambda expected_pid: False)
    opener.open.side_effect = [
        response(b"ok"),
        response(b"<title>Streamlit</title><script>window.prerenderReady = false</script>"),
    ]
    assert launcher.probe_creator() == "occupied"


def test_command_identity_requires_current_repository(tmp_path):
    current_app = str(launcher.ROOT_DIR / "web" / "app.py")
    assert launcher.is_creator_command(["python", "-m", "streamlit", "run", current_app])
    assert launcher.is_creator_command(["streamlit", "run", current_app])
    assert not launcher.is_creator_command(["python", "-m", "streamlit", "run", str(tmp_path / "app.py")])
    assert not launcher.is_creator_command(["python", "-m", "other_module", "run", current_app])
    assert not launcher.is_creator_command(["python", "-m", "streamlit", "run", "web/app.py"])
    assert launcher.is_creator_command(
        ["python", "-m", "streamlit", "run", "web/app.py"], str(launcher.ROOT_DIR)
    )
    assert not launcher.is_creator_command([])


def test_process_identity_rejects_different_pid_and_unreadable_process(monkeypatch):
    # 三个平台使用同一判定逻辑，测试不查询实际机器进程。
    script = str(launcher.ROOT_DIR / "web" / "app.py")
    records = [(123, ["python", "-m", "streamlit", "run", script], None)]
    for name in ("_windows_listeners", "_linux_listeners", "_macos_listeners"):
        monkeypatch.setattr(launcher, name, lambda: records)
    assert launcher.creator_process_matches()
    assert launcher.creator_process_matches(expected_pid=123)
    assert not launcher.creator_process_matches(expected_pid=456)
    records.clear()
    assert not launcher.creator_process_matches()
    for name in ("_windows_listeners", "_linux_listeners", "_macos_listeners"):
        monkeypatch.setattr(launcher, name, MagicMock(side_effect=PermissionError("denied")))
    assert not launcher.creator_process_matches()


def test_windows_process_query_parses_quoted_absolute_path_without_output(monkeypatch, capsys):
    script = str(launcher.ROOT_DIR / "web" / "app.py")
    completed = MagicMock()
    completed.stdout = launcher.json.dumps({
        "ProcessId": 123,
        "CommandLine": f'"C:\\Program Files\\Python\\python.exe" -m streamlit run "{script}"',
    })
    run = MagicMock(return_value=completed)
    monkeypatch.setattr(launcher.subprocess, "run", run)
    records = launcher._windows_listeners()
    assert records[0][0] == 123
    assert launcher.is_creator_command(records[0][1])
    assert run.call_args.kwargs["capture_output"] is True
    assert capsys.readouterr().out == ""


def test_reuses_existing_service_without_owning_process(monkeypatch):
    monkeypatch.setattr(launcher, "probe_creator", lambda: "streamlit")
    popen = MagicMock()
    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    with launcher.creator_service() as child:
        assert child is None
    popen.assert_not_called()


def test_unknown_service_is_not_reused_or_stopped(monkeypatch):
    monkeypatch.setattr(launcher, "probe_creator", lambda: "occupied")
    popen = MagicMock()
    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    with pytest.raises(RuntimeError, match="非预期服务占用"):
        with launcher.creator_service():
            pytest.fail("未知服务占用时不能继续启动")
    popen.assert_not_called()


def test_created_child_uses_current_python_and_is_stopped_on_exit(monkeypatch):
    statuses = iter(["free", "streamlit"])
    monkeypatch.setattr(launcher, "probe_creator", lambda **kwargs: next(statuses))
    child = MagicMock()
    child.poll.return_value = None
    popen = MagicMock(return_value=child)
    monkeypatch.setattr(launcher.subprocess, "Popen", popen)
    with launcher.creator_service() as owned:
        assert owned is child
        child.terminate.assert_not_called()
    child.terminate.assert_called_once()
    child.wait.assert_called_once_with(timeout=5)
    command = popen.call_args.args[0]
    assert command[:4] == [launcher.sys.executable, "-m", "streamlit", "run"]
    assert command[command.index("--server.address") + 1] == "127.0.0.1"
    assert command[command.index("--server.port") + 1] == "8501"
    assert command[command.index("--server.headless") + 1] == "true"
    assert popen.call_args.kwargs["cwd"] == launcher.ROOT_DIR
    if launcher.os.name == "nt":
        assert popen.call_args.kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_startup_failure_does_not_enter_application(monkeypatch):
    monkeypatch.setattr(launcher, "probe_creator", lambda: "free")
    child = MagicMock()
    child.poll.return_value = 1
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: child)
    with pytest.raises(RuntimeError, match="退出码 1"):
        with launcher.creator_service():
            pytest.fail("子服务启动失败时不能进入应用")
    child.terminate.assert_not_called()


def test_startup_timeout_cleans_only_created_child(monkeypatch):
    monkeypatch.setattr(launcher, "probe_creator", lambda: "free")
    child = MagicMock()
    child.poll.return_value = None
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: child)
    with pytest.raises(RuntimeError, match="启动超时"):
        with launcher.creator_service(startup_timeout=0):
            pytest.fail("超时后不能进入应用")
    child.terminate.assert_called_once()


def test_owned_child_is_cleaned_when_application_raises(monkeypatch):
    statuses = iter(["free", "streamlit"])
    monkeypatch.setattr(launcher, "probe_creator", lambda **kwargs: next(statuses))
    child = MagicMock()
    child.poll.return_value = None
    child.wait.side_effect = [subprocess.TimeoutExpired("streamlit", 5), 0]
    monkeypatch.setattr(launcher.subprocess, "Popen", lambda *args, **kwargs: child)
    with pytest.raises(ValueError, match="application failed"):
        with launcher.creator_service():
            raise ValueError("application failed")
    child.terminate.assert_called_once()
    child.kill.assert_called_once()
    assert child.wait.call_count == 2


@pytest.mark.parametrize("port", ["8501", "0", "70000", "bad-port"])
def test_invalid_api_port_never_starts_creator(monkeypatch, port):
    monkeypatch.setenv("FRAMEWEAVE_PORT", port)
    service = MagicMock()
    monkeypatch.setattr(launcher, "creator_service", service)
    assert launcher.main() == 1
    service.assert_not_called()


def test_occupied_api_port_never_starts_creator(monkeypatch):
    monkeypatch.setenv("FRAMEWEAVE_PORT", "8765")
    monkeypatch.setattr(launcher, "port_is_open", lambda port: True)
    service = MagicMock()
    monkeypatch.setattr(launcher, "creator_service", service)
    assert launcher.main() == 1
    service.assert_not_called()


def test_main_runs_api_inside_creator_lifetime(monkeypatch):
    import uvicorn

    monkeypatch.setenv("FRAMEWEAVE_PORT", "8766")
    monkeypatch.setattr(launcher, "port_is_open", lambda port: False)
    events = []

    @contextmanager
    def service():
        events.append("creator-ready")
        yield
        events.append("creator-stopped")

    def run(app, **kwargs):
        assert app == "frameweave.app:create_app"
        assert kwargs["host"] == "127.0.0.1"
        assert kwargs["port"] == 8766
        assert events == ["creator-ready"]
        events.append("api-returned")

    monkeypatch.setattr(launcher, "creator_service", service)
    monkeypatch.setattr(uvicorn, "run", run)
    assert launcher.main() == 0
    assert events == ["creator-ready", "api-returned", "creator-stopped"]
