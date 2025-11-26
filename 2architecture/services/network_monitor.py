import socket
import threading
from typing import Callable, Iterable, Optional, Set

from domain.states import StoryBoxState


class NetworkMonitor:
    """Poll network connectivity and notify listeners of state changes."""

    def __init__(
        self,
        state_provider: Callable[[], StoryBoxState],
        on_online: Callable[[], None],
        on_offline: Callable[[], None],
        interval: float = 10.0,
        skip_states: Optional[Iterable[StoryBoxState]] = None,
        probe_host: str = "8.8.8.8",
        probe_port: int = 53,
        probe_timeout: float = 3.0,
    ) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        if probe_timeout <= 0:
            raise ValueError("probe_timeout must be positive")

        self._state_provider = state_provider
        self._on_online = on_online
        self._on_offline = on_offline
        self._interval = interval
        self._skip_states: Set[StoryBoxState] = set(skip_states or ())
        self._probe_host = probe_host
        self._probe_port = probe_port
        self._probe_timeout = probe_timeout

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_status: Optional[bool] = None
        self._skip_sleep = min(interval, 1.0)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="NetworkMonitor", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self._thread:
            return
        self._stop_event.set()
        self._thread.join(timeout=self._interval)
        self._thread = None

    # ----- internals -----

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                state = self._state_provider()
                if state in self._skip_states:
                    if self._stop_event.wait(self._skip_sleep):
                        break
                    continue

                is_online = self._check_connectivity()
                self._handle_status(is_online)
            except Exception as exc:  # noqa: BLE001
                print(f"[NetworkMonitor] Error during polling: {exc}")

            if self._stop_event.wait(self._interval):
                break

    def _handle_status(self, is_online: bool) -> None:
        if is_online:
            if self._last_status is not True:
                self._invoke_callback(self._on_online, "on_online")
            self._last_status = True
        else:
            self._invoke_callback(self._on_offline, "on_offline")
            self._last_status = False

    def _invoke_callback(self, callback: Callable[[], None], label: str) -> None:
        try:
            callback()
        except Exception as exc:  # noqa: BLE001
            print(f"[NetworkMonitor] Callback '{label}' raised: {exc}")

    def _check_connectivity(self) -> bool:
        sock: Optional[socket.socket] = None
        try:
            sock = socket.create_connection((self._probe_host, self._probe_port), timeout=self._probe_timeout)
            return True
        except OSError:
            return False
        finally:
            if sock:
                try:
                    sock.close()
                except OSError:
                    pass
