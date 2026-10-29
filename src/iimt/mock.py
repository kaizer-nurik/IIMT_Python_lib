"""External TCP CI-05 protocol simulator. No controller-side mock implementation."""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import re
import socketserver
import threading
import time
from collections import deque
from pathlib import Path

DEFAULT_Q = [0.0, -1.5707963267949, 0.0, -1.5707963267949, 0.0, 0.0]


class _State:
    def __init__(self, options):
        self.q = list(options.get("positions", DEFAULT_Q))
        self.options = options
        self.lock = threading.Lock()
        self.queue = deque(maxlen=4096)
        self.reads = 0
        self.log = Path(options["log"]).open("a", buffering=1) if options.get("log") else None

    def record(self, kind, **values):
        if self.log:
            self.log.write(
                json.dumps(
                    {
                        "kind": kind,
                        "unix_ns": time.time_ns(),
                        # CPython 3.12 Windows monotonic uses coarse GetTickCount64;
                        # perf_counter uses QPC. Keep UTC separate from interval time.
                        "monotonic_ns": time.perf_counter_ns(),
                        **values,
                    }
                )
                + "\n"
            )

    def apply_due(self):
        now = time.perf_counter()
        while self.queue and self.queue[0][0] <= now:
            _, self.q = self.queue.popleft()


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        state = self.server.state
        self.wfile.write(b"Connected: Universal Robots Dashboard Server\n")
        while raw := self.rfile.readline(4097):
            if len(raw) > 4096:
                return
            command = raw.decode("ascii", errors="replace").strip()
            reply = None
            delay = 0.0
            with state.lock:
                state.apply_due()
                if command.startswith("servoj("):
                    values = re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", command)
                    if len(values) != 11:
                        return
                    q = list(map(float, values[:6]))
                    state.queue.append((time.perf_counter() + state.options.get("lag", 0.0), q))
                    state.record("servoj", positions=q, parameters=list(map(float, values[6:])))
                elif command == "get joint rad":
                    state.reads += 1
                    delay = state.options.get("read_delay", 0.0)
                    every = state.options.get("timeout_every", 0)
                    if every and state.reads % every == 0:
                        delay += state.options.get("timeout_delay", 0.3)
                    # Snapshot at query handling, receipt timestamp is deliberately later.
                    reply = "Joint radian " + ",".join(f"{q:.9f}" for q in state.q) + "\n"
                    state.record("read", positions=state.q)
                elif command == "stop":
                    state.queue.clear()
                    state.record("stop")
                    reply = "Failure\n" if state.options.get("fail_stop") else "Stopped\n"
                elif command == "programState":
                    reply = "RUNNING mock\n" if state.options.get("fail_stop") else "STOPPED mock\n"
                elif command == "unlock protective stop":
                    state.queue.clear()
                    state.record("clear")
                    reply = (
                        "Failure\n"
                        if state.options.get("fail_clear")
                        else "Protective stop releasing\n"
                    )
                else:
                    state.record("unknown", command=command)
                    reply = "Unknown command\n"
            if delay:
                time.sleep(delay)
            if reply is not None:
                try:
                    self.wfile.write(reply.encode("ascii"))
                except (BrokenPipeError, ConnectionResetError):
                    return


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def handle_error(self, request, client_address):
        # Disconnects are expected on bounded client read timeout.
        pass


def _serve(host, port, options, ready=None, commands=None):
    with _Server((host, port), _Handler) as server:
        server.state = _State(options)
        server.timeout = 0.05
        if ready:
            ready.send(server.server_address)
            ready.close()
        try:
            while True:
                if commands and commands.poll():
                    update = commands.recv()
                    if update is None:
                        break
                    with server.state.lock:
                        server.state.options.update(update)
                parent = mp.parent_process()
                if parent is not None and not parent.is_alive():
                    break
                server.handle_request()
        finally:
            if server.state.log:
                server.state.log.close()


class MockRobot:
    """Runs a real external server process; use its host/port in the usual Arm."""

    def __init__(self, host="127.0.0.1", port=0, **options):
        self.host, self.port, self.options = host, port, options
        self._process = None

    def start(self):
        if self._process is not None:
            raise RuntimeError("Mock already started")
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        self._commands, commands = ctx.Pipe()
        self._process = ctx.Process(
            target=_serve, args=(self.host, self.port, self.options, child, commands), daemon=True
        )
        self._process.start()
        child.close()
        commands.close()
        if not parent.poll(10):
            self.close()
            raise TimeoutError("Mock server did not start")
        self.host, self.port = parent.recv()
        parent.close()
        return self

    def set_faults(self, **options):
        self._commands.send(options)

    def close(self):
        if self._process is None:
            return
        if self._process.is_alive():
            self._commands.send(None)
            self._process.join(2)
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(2)
        self._commands.close()
        self._process = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=29999)
    parser.add_argument("--lag", type=float, default=0.0)
    parser.add_argument("--read-delay", type=float, default=0.0)
    parser.add_argument("--log")
    args = vars(parser.parse_args())
    host = args.pop("host")
    port = args.pop("port")
    print(f"Mock listening on {host}:{port}; SDK-compatible sockets", flush=True)
    try:
        _serve(host, port, args)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
