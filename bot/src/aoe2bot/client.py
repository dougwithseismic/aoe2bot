"""IPC clients for communicating with AoE2Control's Lua module.

Two transports:
  - AoE2Client: direct named pipe (requires pywin32, Windows-only)
  - TcpClient: connects to the TCP bridge (cross-platform, works from Claude)
"""

from __future__ import annotations

import json
import socket
import time
import logging
import itertools
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from .protocol import PIPE_NAME

logger = logging.getLogger(__name__)

_counter = itertools.count(1)

TCP_HOST = "127.0.0.1"
TCP_PORT = 9999


class ConnectionError(Exception):
    pass


class TimeoutError(Exception):
    pass


# ── TCP Client (connects to bridge) ─────────────────────────────────────────


@dataclass
class TcpClient:
    """Connects to the TCP bridge server. Same interface as AoE2Client."""

    host: str = TCP_HOST
    port: int = TCP_PORT
    target_player: int | None = None
    _sock: socket.socket | None = field(default=None, init=False, repr=False)
    _connected: bool = field(default=False, init=False)
    _buf: bytes = field(default=b"", init=False, repr=False)

    def connect(self, timeout_ms: int = 5000) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(timeout_ms / 1000)
        try:
            self._sock.connect((self.host, self.port))
            self._connected = True
            self._buf = b""
        except (OSError, socket.timeout) as e:
            raise ConnectionError(
                f"Cannot connect to bridge at {self.host}:{self.port}. "
                f"Is 'aoe2bot bridge' running? Error: {e}"
            ) from e

    def disconnect(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def request(self, payload: dict, timeout_s: float = 10.0) -> dict:
        if not self._connected or not self._sock:
            raise ConnectionError("Not connected to bridge")

        if self.target_player is not None and "target" not in payload:
            payload["_target_player"] = self.target_player

        data = json.dumps(payload, separators=(",", ":")).encode("utf-8") + b"\n"
        try:
            self._sock.sendall(data)
        except OSError as e:
            self._connected = False
            raise ConnectionError(f"Send failed: {e}") from e

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if b"\n" in self._buf:
                line, self._buf = self._buf.split(b"\n", 1)
                return json.loads(line)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._sock.settimeout(remaining)
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout:
                break
            except OSError as e:
                self._connected = False
                raise ConnectionError(f"Read failed: {e}") from e
            if not chunk:
                self._connected = False
                raise ConnectionError("Bridge closed connection")
            self._buf += chunk

        raise TimeoutError(f"No response within {timeout_s}s")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.disconnect()


# ── Named Pipe Client (direct, Windows-only) ────────────────────────────────


@dataclass
class AoE2Client:
    """Low-level IPC client for the AoE2Bot Lua bridge module (named pipe)."""

    pipe_name: str = PIPE_NAME
    target_player: int | None = None
    _handle: Any = field(default=None, init=False, repr=False)
    _connected: bool = field(default=False, init=False)
    _inbox: deque = field(default_factory=deque, init=False, repr=False)

    def connect(self, timeout_ms: int = 10000) -> None:
        import win32file as _wf, win32pipe as _wp, pywintypes as _pwt
        try:
            _wp.WaitNamedPipe(self.pipe_name, timeout_ms)
        except _pwt.error as e:
            raise ConnectionError(
                f"Pipe '{self.pipe_name}' not available. "
                f"Is AoE2:DE running with AoE2Control attached and the aoe2bot module loaded? Error: {e}"
            ) from e
        try:
            self._handle = _wf.CreateFile(
                self.pipe_name,
                _wf.GENERIC_READ | _wf.GENERIC_WRITE,
                0, None, _wf.OPEN_EXISTING, 0, None,
            )
            _wp.SetNamedPipeHandleState(
                self._handle, _wp.PIPE_READMODE_MESSAGE, None, None,
            )
            self._connected = True
            self._inbox.clear()
        except _pwt.error as e:
            raise ConnectionError(f"Failed to open pipe: {e}") from e

    def disconnect(self) -> None:
        import win32file as _wf
        if self._handle is not None:
            try:
                _wf.CloseHandle(self._handle)
            except Exception:
                pass
            self._handle = None
        self._connected = False
        self._inbox.clear()

    @property
    def connected(self) -> bool:
        return self._connected

    def _read_one(self, timeout_s: float = 0.5) -> dict | None:
        """Read one message from the pipe, or None on timeout."""
        import win32file as _wf, pywintypes as _pwt
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                _, data = _wf.ReadFile(self._handle, 65536)
                msg = json.loads(data.decode("utf-8"))
                return msg.get("payload", msg)
            except _pwt.error as e:
                if e.args[0] == 232:  # ERROR_NO_DATA
                    time.sleep(0.02)
                    continue
                self._connected = False
                raise ConnectionError(f"Read failed: {e}") from e
        return None

    def _drain(self) -> None:
        """Read all available messages into inbox."""
        while True:
            msg = self._read_one(timeout_s=0.1)
            if msg is None:
                break
            self._inbox.append(msg)

    def send(self, payload: dict, target: dict | None = None) -> None:
        import win32file as _wf, pywintypes as _pwt
        if not self._connected:
            raise ConnectionError("Not connected")

        message: dict[str, Any] = {}
        if target:
            message["target"] = target
        elif self.target_player is not None:
            message["target"] = {"assignedPlayerId": self.target_player}
        message["payload"] = payload

        data = json.dumps(message, separators=(",", ":")).encode("utf-8")
        try:
            _wf.WriteFile(self._handle, data)
        except _pwt.error as e:
            self._connected = False
            raise ConnectionError(f"Write failed: {e}") from e

    def request(self, payload: dict, timeout_s: float = 5.0) -> dict:
        """Send a command and wait for the matching response (by reqId)."""
        req_id = next(_counter)
        payload["reqId"] = req_id
        self.send(payload)

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            for i, msg in enumerate(self._inbox):
                if msg.get("reqId") == req_id:
                    del self._inbox[i]
                    return msg

            msg = self._read_one(timeout_s=min(0.5, deadline - time.monotonic()))
            if msg is not None:
                if msg.get("reqId") == req_id:
                    return msg
                if msg.get("reqId") is None:
                    return msg
                self._inbox.append(msg)

        raise TimeoutError(f"No response for reqId={req_id} within {timeout_s}s")

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.disconnect()
