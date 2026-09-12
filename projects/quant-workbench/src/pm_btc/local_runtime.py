from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from typing import IO


@dataclass(frozen=True)
class ComponentSpec:
    name: str
    command: tuple[str, ...]
    cwd: Path


def component_specs(project_root: Path, database: str) -> tuple[ComponentSpec, ...]:
    """Return the safe local research stack; no paper or live broker is started."""
    python = str(Path(sys.executable).resolve())
    database_path = str((project_root / database).resolve())
    module = (python, "-m", "pm_btc.cli")
    worker_commands = (
        ("polymarket-books", (*module, "run-polymarket-books", "--database", database_path)),
        ("polymarket-discovery", (*module, "run-polymarket-discovery", "--database", database_path)),
        ("polymarket-clob-ws", (*module, "run-polymarket-clob-ws", "--database", database_path)),
        ("chainlink-rtds", (*module, "run-chainlink-rtds", "--database", database_path)),
        ("binance-http", (*module, "run-binance-http", "--database", database_path)),
        ("binance-ws", (*module, "run-binance-ws", "--database", database_path)),
        ("research", (*module, "run-research", "--database", database_path)),
        ("auto-model", (*module, "run-auto-model", "--database", database_path)),
        ("risk-monitor", (*module, "run-risk-monitor", "--database", database_path)),
        ("api", (*module, "serve-api", "--database", database_path, "--port", "8000")),
    )
    npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm.cmd"
    specs = [ComponentSpec(name, tuple(command), project_root) for name, command in worker_commands]
    specs.append(ComponentSpec("web", (npm, "run", "start"), project_root / "web"))
    return tuple(specs)


def validate_local_runtime(project_root: Path) -> list[str]:
    errors: list[str] = []
    if not (project_root / "data").is_dir():
        errors.append("data directory missing")
    if not (project_root / "web" / "package.json").is_file():
        errors.append("web/package.json missing")
    if not (project_root / "web" / "node_modules").is_dir():
        errors.append("web dependencies missing; run npm install in web")
    try:
        import httpx  # noqa: F401
        import websockets  # noqa: F401
        import zstandard  # noqa: F401
    except ImportError as error:
        errors.append(f"python dependency missing: {error.name}; install the project into .venv")
    return errors


class LocalSupervisor:
    def __init__(self, project_root: Path, database: str = "data/live.sqlite3") -> None:
        self.project_root = project_root.resolve()
        self.database = database
        self.run_dir = self.project_root / "run"
        self.log_dir = self.project_root / "logs"
        self.manifest_path = self.run_dir / "local-runtime.json"
        self.lock_path = self.run_dir / "local-runtime.lock"
        self.specs = component_specs(self.project_root, database)
        self.processes: dict[str, subprocess.Popen[bytes]] = {}
        self.log_files: dict[str, tuple[IO[bytes], IO[bytes]]] = {}
        self.restart_count: dict[str, int] = {spec.name: 0 for spec in self.specs}
        self.next_restart_at: dict[str, float] = {spec.name: 0.0 for spec in self.specs}
        self.stopping = False
        self._lock_file: IO[bytes] | None = None

    def _acquire_lock(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._lock_file = self.lock_path.open("a+b")
        if os.name == "nt":
            import msvcrt

            try:
                if self.lock_path.stat().st_size == 0:
                    self._lock_file.write(b"0")
                    self._lock_file.flush()
                self._lock_file.seek(0)
                msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise RuntimeError("local runtime is already supervised") from error
        else:
            import fcntl

            try:
                fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise RuntimeError("local runtime is already supervised") from error

    def _start(self, spec: ComponentSpec) -> None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        stdout = (self.log_dir / f"local-{spec.name}-{stamp}.out.log").open("ab")
        stderr = (self.log_dir / f"local-{spec.name}-{stamp}.err.log").open("ab")
        environment = os.environ.copy()
        environment["PYTHONUNBUFFERED"] = "1"
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            spec.command,
            cwd=spec.cwd,
            env=environment,
            stdout=stdout,
            stderr=stderr,
            creationflags=creationflags,
        )
        self.processes[spec.name] = process
        self.log_files[spec.name] = (stdout, stderr)
        self._write_manifest()

    def _close_logs(self, name: str) -> None:
        for handle in self.log_files.pop(name, ()):
            handle.close()

    def _write_manifest(self) -> None:
        payload = {
            "supervisor_pid": os.getpid(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "database": str((self.project_root / self.database).resolve()),
            "mode": "RESEARCH_ONLY",
            "components": {
                spec.name: {
                    "pid": self.processes.get(spec.name).pid if spec.name in self.processes else None,
                    "running": spec.name in self.processes and self.processes[spec.name].poll() is None,
                    "restart_count": self.restart_count[spec.name],
                }
                for spec in self.specs
            },
        }
        temporary = self.manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.manifest_path)

    def _request_stop(self, *_: object) -> None:
        self.stopping = True

    def run_forever(self) -> None:
        errors = validate_local_runtime(self.project_root)
        if errors:
            raise RuntimeError("; ".join(errors))
        self._acquire_lock()
        # Complete schema work before concurrent writers start.  Without this
        # barrier every child can contend on CREATE INDEX during a cold start.
        from .storage import SQLiteStore

        database_store = SQLiteStore(str((self.project_root / self.database).resolve()))
        database_store.close()
        signal.signal(signal.SIGINT, self._request_stop)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, self._request_stop)
        for spec in self.specs:
            self._start(spec)
            time.sleep(0.35)
        try:
            while not self.stopping:
                now = time.monotonic()
                for spec in self.specs:
                    process = self.processes.get(spec.name)
                    if process is not None and process.poll() is None:
                        continue
                    if process is not None:
                        self._close_logs(spec.name)
                        self.processes.pop(spec.name, None)
                        self.restart_count[spec.name] += 1
                        delay = min(30.0, 2.0 ** min(self.restart_count[spec.name], 5))
                        self.next_restart_at[spec.name] = now + delay
                    if now >= self.next_restart_at[spec.name]:
                        self._start(spec)
                self._write_manifest()
                time.sleep(2.0)
        finally:
            self.stopping = True
            for process in self.processes.values():
                if process.poll() is None:
                    process.terminate()
            deadline = time.monotonic() + 10.0
            for process in self.processes.values():
                remaining = max(0.0, deadline - time.monotonic())
                try:
                    process.wait(timeout=remaining)
                except subprocess.TimeoutExpired:
                    process.kill()
            for name in tuple(self.log_files):
                self._close_logs(name)
            self._write_manifest()
            if self._lock_file is not None:
                self._lock_file.close()


def local_status(project_root: Path) -> dict:
    path = project_root.resolve() / "run" / "local-runtime.json"
    if not path.is_file():
        return {"status": "NOT_STARTED", "manifest": str(path)}
    payload = json.loads(path.read_text(encoding="utf-8"))
    components = payload.get("components", {})
    payload["status"] = "RUNNING" if components and all(
        component.get("running") for component in components.values()
    ) else "DEGRADED"
    return payload
