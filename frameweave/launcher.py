"""统一启动镜织和原有创作页面，只管理本次启动的子进程。"""

import json
import os
import shlex
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

HOST = "127.0.0.1"
CREATOR_PORT = 8501
ROOT_DIR = Path(__file__).resolve().parent.parent


def is_creator_command(arguments: list[str], cwd: str | None = None) -> bool:
    """只接受运行本仓库 web/app.py 的 Streamlit；相对路径必须有可信 cwd。"""
    try:
        if "-m" in arguments:
            module_index = arguments.index("-m")
            if arguments[module_index + 1 : module_index + 3] != ["streamlit", "run"]:
                return False
            script = arguments[module_index + 3]
        elif Path(arguments[0]).stem.lower() == "streamlit" and arguments[1] == "run":
            script = arguments[2]
        else:
            return False
        path = Path(script)
        if not path.is_absolute():
            if cwd is None:
                return False
            path = Path(cwd) / path
        return path.resolve() == (ROOT_DIR / "web" / "app.py").resolve()
    except (IndexError, OSError, ValueError):
        return False


def _windows_listeners() -> list[tuple[int, list[str], str | None]]:
    """通过系统只读查询定位监听进程；命令行只在内存中比较，绝不输出。"""
    script = (
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new(); "
        "$ErrorActionPreference='Stop'; "
        f"$owners = Get-NetTCPConnection -LocalPort {CREATOR_PORT} -State Listen | "
        "Where-Object { $_.LocalAddress -in @('127.0.0.1','0.0.0.0','::','::1') } | "
        "Select-Object -ExpandProperty OwningProcess -Unique; "
        "@($owners | ForEach-Object { Get-CimInstance Win32_Process -Filter "
        "\"ProcessId = $_\" | Select-Object ProcessId, CommandLine }) | ConvertTo-Json -Compress"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    records = json.loads(result.stdout or "[]")
    if isinstance(records, dict):
        records = [records]
    return [
        (
            int(item["ProcessId"]),
            [part.strip('"') for part in shlex.split(item.get("CommandLine") or "", posix=False)],
            None,
        )
        for item in records or []
    ]


def _linux_listeners() -> list[tuple[int, list[str], str | None]]:
    """以 /proc 的监听 socket inode 关联 PID，再校验脚本与实际工作目录。"""
    inodes = set()
    for name in ("tcp", "tcp6"):
        for line in Path(f"/proc/net/{name}").read_text().splitlines()[1:]:
            fields = line.split()
            address, port = fields[1].split(":")
            if int(port, 16) == CREATOR_PORT and fields[3] == "0A" and address in {
                "0100007F", "00000000", "00000000000000000000000000000000",
                "00000000000000000000000001000000",
            }:
                inodes.add(f"socket:[{fields[9]}]")
    records = []
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            if not any(os.readlink(fd) in inodes for fd in (process / "fd").iterdir()):
                continue
            arguments = [part.decode("utf-8") for part in (process / "cmdline").read_bytes().split(b"\0") if part]
            records.append((int(process.name), arguments, os.readlink(process / "cwd")))
        except (OSError, UnicodeError):
            # /proc 权限不足或进程已退出时不能证明归属，交给调用方拒绝复用。
            continue
    return records


def _macos_listeners() -> list[tuple[int, list[str], str | None]]:
    """使用 macOS 自带只读命令查询 PID；无权限时由调用方拒绝复用。"""
    result = subprocess.run(
        ["lsof", "-nP", f"-iTCP:{CREATOR_PORT}", "-sTCP:LISTEN", "-Fp"],
        capture_output=True, text=True, timeout=5, check=True,
    )
    records = []
    for value in set(result.stdout.splitlines()):
        if not value.startswith("p"):
            continue
        pid = int(value[1:])
        command = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True, text=True, timeout=5, check=True,
        )
        cwd_result = subprocess.run(
            ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
            capture_output=True, text=True, timeout=5, check=True,
        )
        cwd = next((line[1:] for line in cwd_result.stdout.splitlines() if line.startswith("n")), None)
        records.append((pid, shlex.split(command.stdout), cwd))
    return records


def creator_process_matches(expected_pid: int | None = None) -> bool:
    """必须证明监听者属于本仓库；读取受限或匹配不明时拒绝复用。"""
    try:
        if os.name == "nt":
            records = _windows_listeners()
        elif sys.platform == "linux":
            records = _linux_listeners()
        elif sys.platform == "darwin":
            records = _macos_listeners()
        else:
            return False
        return bool(records) and all(
            (expected_pid is None or pid == expected_pid) and is_creator_command(arguments, cwd)
            for pid, arguments, cwd in records
        )
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        return False


def port_is_open(port: int) -> bool:
    """只检查本机 TCP 端口，不修改已有进程。"""
    try:
        with socket.create_connection((HOST, port), timeout=0.5):
            return True
    except OSError:
        return False


def probe_creator(expected_pid: int | None = None) -> str:
    """区分空闲端口、可复用 Streamlit 与未知占用服务。"""
    if not port_is_open(CREATOR_PORT):
        return "free"

    # 本机探测不使用系统代理，避免代理设置将健康检查发到外网。
    opener = build_opener(ProxyHandler({}))
    try:
        health = Request(f"http://{HOST}:{CREATOR_PORT}/_stcore/health")
        with opener.open(health, timeout=1) as response:
            healthy = response.status == 200 and response.read(32).strip() == b"ok"
        page = Request(f"http://{HOST}:{CREATOR_PORT}/")
        with opener.open(page, timeout=1) as response:
            html = response.read(65536).decode("utf-8", errors="replace")
        # 同时检查 Streamlit 页面特征，不能把任意返回 ok 的 HTTP 服务当成创作页。
        if (
            healthy
            and "<title>Streamlit</title>" in html
            and "window.prerenderReady" in html
            and creator_process_matches(expected_pid)
        ):
            return "streamlit"
    except (OSError, ValueError):
        pass
    return "occupied"


def stop_owned_child(child: subprocess.Popen) -> None:
    """只结束本启动器创建的 Streamlit，绝不按端口或进程名清理服务。"""
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


@contextmanager
def creator_service(startup_timeout: float = 30):
    """复用已运行的 Streamlit，或启动一个随工作台退出的隐藏子进程。"""
    status = probe_creator()
    if status == "streamlit":
        print(f"[镜织] 复用已有创作服务 http://{HOST}:{CREATOR_PORT}，退出时保留该服务。")
        yield None
        return
    if status == "occupied":
        raise RuntimeError(
            f"端口 {CREATOR_PORT} 已被非预期服务占用，或无法确认监听进程属于本仓库。"
            "请检查进程权限和启动脚本路径；已有服务需使用本仓库 web/app.py 的绝对路径启动。"
            "镜织不会停止已有进程。"
        )

    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(ROOT_DIR / "web" / "app.py"),
        "--server.address",
        HOST,
        "--server.port",
        str(CREATOR_PORT),
        "--server.headless",
        "true",
        "--browser.gatherUsageStats",
        "false",
    ]
    # Windows 不弹出第二个终端；日志仍跟随启动器，方便查看真实启动错误。
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    child = subprocess.Popen(
        command,
        cwd=ROOT_DIR,
        stdin=subprocess.DEVNULL,
        creationflags=flags,
    )
    try:
        deadline = time.monotonic() + startup_timeout
        while time.monotonic() < deadline:
            exit_code = child.poll()
            if exit_code is not None:
                raise RuntimeError(f"原有创作服务启动失败（退出码 {exit_code}），请查看上方日志。")
            if probe_creator(expected_pid=child.pid) == "streamlit":
                print(f"[镜织] 创作服务已就绪 http://{HOST}:{CREATOR_PORT}。")
                yield child
                return
            time.sleep(0.25)
        raise RuntimeError("原有创作服务启动超时，请检查 Streamlit 依赖和上方日志。")
    finally:
        stop_owned_child(child)


def main() -> int:
    """一个命令启动统一视频工作台与创作服务，启动失败时给出明确原因。"""
    import uvicorn

    try:
        port = int(os.environ.get("FRAMEWEAVE_PORT", "8765"))
        if not 1 <= port <= 65535 or port == CREATOR_PORT:
            raise ValueError(f"FRAMEWEAVE_PORT 应为 1–65535，且不能使用创作服务端口 {CREATOR_PORT}。")
        if port_is_open(port):
            raise RuntimeError(f"镜织端口 {port} 已被占用。请打开现有工作台，或设置其他 FRAMEWEAVE_PORT。")
        with creator_service():
            uvicorn.run(
                "frameweave.app:create_app",
                factory=True,
                host=HOST,
                port=port,
                workers=1,
            )
        return 0
    except (OSError, ValueError, RuntimeError) as error:
        print(f"[镜织启动失败] {error}", file=sys.stderr)
        return 1

