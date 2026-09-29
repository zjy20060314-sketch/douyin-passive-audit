"""Visible Edge adapter for passive Douyin Web collection."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, TextIO

from ..models import Account, AuditError, RawObservation, now
from .base import BasePlatformAdapter


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _first_existing(*paths: Path) -> Path:
    return next((path for path in paths if path.exists()), paths[0])


def default_edge_path() -> Path:
    override = os.environ.get("DOUYIN_AUDIT_EDGE")
    if override:
        return Path(override).expanduser()
    return _first_existing(
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) /
        "Microsoft/Edge/Application/msedge.exe",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) /
        "Microsoft/Edge/Application/msedge.exe",
    )


def default_node_path() -> Path:
    override = os.environ.get("DOUYIN_AUDIT_NODE")
    if override:
        return Path(override).expanduser()
    discovered = shutil.which("node")
    return Path(discovered) if discovered else Path("node")


def default_node_modules() -> Path:
    override = os.environ.get("DOUYIN_AUDIT_NODE_MODULES")
    return Path(override).expanduser() if override else PROJECT_ROOT / "node_modules"


class DouyinAdapter(BasePlatformAdapter):
    """Human-paced, visible browser adapter for one dedicated test profile."""

    synthetic = False

    def __init__(self, *, output_dir: Path | None = None, profile_dir: Path | None = None,
                 edge_path: Path | None = None, node_path: Path | None = None,
                 node_modules: Path | None = None, open_timeout_seconds: float = 45.0,
                 login_wait_seconds: float = 0.0, capture_screenshots: bool = False):
        self.output_dir = (output_dir or PROJECT_ROOT / "data_live_debug").resolve()
        self.profile_dir = (profile_dir or PROJECT_ROOT / "runtime/douyin-edge-profile").resolve()
        self.edge_path = edge_path or default_edge_path()
        self.node_path = node_path or default_node_path()
        self.node_modules = node_modules or default_node_modules()
        self.open_timeout_seconds = open_timeout_seconds
        self.login_wait_seconds = login_wait_seconds
        self.capture_screenshots = capture_screenshots
        self.process: subprocess.Popen[str] | None = None
        self._stderr_thread: threading.Thread | None = None
        self._stderr_lines: list[str] = []
        self._request_id = 0
        self._position = 0
        self._session_id = ""

    def _drain_stderr(self, stream: TextIO) -> None:
        for line in stream:
            self._stderr_lines.append(line.rstrip())
            if len(self._stderr_lines) > 100:
                self._stderr_lines.pop(0)

    def _start(self) -> None:
        if self.process is not None:
            return
        for path, label in ((self.edge_path, "Edge"), (self.node_path, "Node.js"),
                            (self.node_modules / "playwright", "Playwright")):
            if not path.exists():
                raise AuditError("BROWSER_RUNTIME_MISSING", f"未找到{label}: {path}")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["NODE_PATH"] = str(self.node_modules)
        bridge = Path(__file__).with_name("douyin_edge_bridge.cjs")
        self.process = subprocess.Popen(
            [str(self.node_path), str(bridge), str(self.edge_path), str(self.profile_dir)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1, env=env,
        )
        assert self.process.stderr is not None
        self._stderr_thread = threading.Thread(target=self._drain_stderr,
                                               args=(self.process.stderr,), daemon=True)
        self._stderr_thread.start()

    def _command(self, action: str, **payload: Any) -> dict[str, Any]:
        self._start()
        assert self.process is not None and self.process.stdin is not None and self.process.stdout is not None
        if self.process.poll() is not None:
            detail = "\n".join(self._stderr_lines[-10:])
            raise AuditError("BROWSER_PROCESS_EXITED", f"Edge桥接进程已退出。{detail}")
        self._request_id += 1
        request = {"id": self._request_id, "action": action, **payload}
        self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            detail = "\n".join(self._stderr_lines[-10:])
            raise AuditError("BROWSER_PROTOCOL_ERROR", f"Edge桥接进程没有返回结果。{detail}")
        response = json.loads(line)
        if response.get("id") != self._request_id:
            raise AuditError("BROWSER_PROTOCOL_ERROR", "浏览器响应序号不匹配")
        if not response.get("ok"):
            error = response.get("error") or {}
            raise AuditError(error.get("code", "BROWSER_AUTOMATION_FAILED"),
                             error.get("message", "Edge自动化失败"),
                             bool(error.get("retryable")))
        return response.get("result") or {}

    def open_session(self, account: Account, session_id: str) -> None:
        self._session_id = session_id
        self._position = 0
        self._command("open", url="https://www.douyin.com/?recommend=1",
                      timeout_ms=round(self.open_timeout_seconds * 1000),
                      login_wait_ms=round(self.login_wait_seconds * 1000),
                      account_id=account.account_id)

    def read_current(self) -> RawObservation:
        self._position += 1
        evidence_path: Path | None = None
        if self.capture_screenshots:
            evidence_dir = self.output_dir / "evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            evidence_path = evidence_dir / f"{self._session_id}_{self._position:03d}.png"
        result = self._command("read_current",
                               evidence_path=str(evidence_path) if evidence_path else None)
        metadata = result.get("metadata") or {}
        token = str(metadata.get("content_id") or "")
        if not token:
            self._position -= 1
            raise AuditError("EXPOSURE_NOT_IDENTIFIED", "当前可见视频没有可核验的抖音内容ID", retryable=True)
        return RawObservation(exposure_token=token, captured_at=now(),
                              metadata=metadata,
                              evidence_path=str(evidence_path) if evidence_path else None)

    def advance_once(self) -> None:
        self._command("advance_once")

    def after_manual_verification(self) -> bool:
        try:
            return bool(self._command("health").get("feed_ready"))
        except AuditError:
            return False

    def close(self) -> None:
        if self.process is None:
            return
        try:
            if self.process.poll() is None:
                self._command("close")
        except (AuditError, BrokenPipeError, json.JSONDecodeError):
            self.process.terminate()
        finally:
            if self.process.stdin is not None:
                self.process.stdin.close()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
