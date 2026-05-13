"""TCP-to-Named-Pipe bridge server.

Sits between Claude (TCP) and the AoE2Control Lua module (named pipe).
Start with: aoe2bot bridge
"""

from __future__ import annotations

import json
import socket
import sys
import logging
import threading
import time

from .client import AoE2Client

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9999


class Bridge:
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        pipe_name: str | None = None,
        target_player: int | None = None,
    ):
        self.host = host
        self.port = port
        self._pipe_kwargs: dict = {}
        if pipe_name:
            self._pipe_kwargs["pipe_name"] = pipe_name
        if target_player is not None:
            self._pipe_kwargs["target_player"] = target_player
        self._pipe: AoE2Client | None = None
        self._pipe_lock = threading.Lock()
        self._server: socket.socket | None = None
        self._running = False

    def _connect_pipe(self) -> None:
        if self._pipe and self._pipe.connected:
            return
        self._pipe = AoE2Client(**self._pipe_kwargs)
        self._pipe.connect()
        logger.info("Connected to named pipe")

    def _pipe_request(self, payload: dict, timeout_s: float = 10.0) -> dict:
        with self._pipe_lock:
            try:
                self._connect_pipe()
                assert self._pipe is not None
                return self._pipe.request(payload, timeout_s=timeout_s)
            except Exception as e:
                logger.error("Pipe request failed: %s", e)
                if self._pipe:
                    try:
                        self._pipe.disconnect()
                    except Exception:
                        pass
                    self._pipe = None
                return {"action": "error", "error": f"pipe error: {e}"}

    def _handle_client(self, conn: socket.socket, addr: tuple) -> None:
        logger.info("TCP client connected: %s", addr)
        buf = b""
        try:
            while self._running:
                try:
                    data = conn.recv(65536)
                except (ConnectionResetError, OSError):
                    break
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        request = json.loads(line)
                    except json.JSONDecodeError as e:
                        err = json.dumps({"action": "error", "error": f"invalid json: {e}"})
                        conn.sendall(err.encode("utf-8") + b"\n")
                        continue

                    timeout = request.pop("_timeout", 10.0)
                    response = self._pipe_request(request, timeout_s=timeout)

                    try:
                        conn.sendall(json.dumps(response, default=str).encode("utf-8") + b"\n")
                    except (BrokenPipeError, OSError):
                        return
        finally:
            conn.close()
            logger.info("TCP client disconnected: %s", addr)

    def run(self) -> None:
        self._running = True

        print(f"Connecting to AoE2Control pipe...")
        try:
            self._connect_pipe()
        except Exception as e:
            print(f"ERROR: Could not connect to pipe: {e}", file=sys.stderr)
            print("Make sure AoE2:DE is running with AoE2Control and the aoe2bot module loaded.")
            sys.exit(1)

        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.settimeout(1.0)
        self._server.bind((self.host, self.port))
        self._server.listen(5)

        print(f"Bridge listening on {self.host}:{self.port}")
        print(f"Send JSON commands over TCP. Example: echo '{{\"action\":\"ping\"}}' | nc localhost {self.port}")

        try:
            while self._running:
                try:
                    conn, addr = self._server.accept()
                    t = threading.Thread(target=self._handle_client, args=(conn, addr), daemon=True)
                    t.start()
                except socket.timeout:
                    continue
        except KeyboardInterrupt:
            print("\nShutting down bridge...")
        finally:
            self._running = False
            if self._server:
                self._server.close()
            if self._pipe:
                self._pipe.disconnect()


def main(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, **kwargs) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    bridge = Bridge(host=host, port=port, **kwargs)
    bridge.run()
