import atexit
import threading
import time
from pathlib import Path
from typing import Optional

import pygame


class AudioPlayer:
    """Stream long-form stories using pygame.mixer.music (low latency)."""

    def __init__(self, on_story_finished_callback=None):
        self._lock = threading.Lock()
        self._paused = False
        self._is_playing = False
        self._current_file: Optional[Path] = None
        self._playback_token = 0
        self._on_story_finished_callback = on_story_finished_callback
        self._last_position: float = 0.0

        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
            print("[AudioPlayer] pygame.mixer initialized.")

        atexit.register(self.stop_story)

    def play_story(self, filepath: str):
        """
        Lance la lecture de l'histoire (en non bloquant).
        Stoppe d'abord toute lecture en cours.
        """
        story_path = Path(filepath).expanduser().resolve()
        if not story_path.is_file():
            print(f"[AudioPlayer] ERROR: story file not found: {story_path}")
            return

        with self._lock:
            self._stop_story_locked()

            print(f"[AudioPlayer] Starting story playback: {story_path}")
            try:
                pygame.mixer.music.load(str(story_path))
                pygame.mixer.music.play(loops=0)
            except Exception as exc:
                print(f"[AudioPlayer] ERROR: failed to start playback: {exc}")
                return

            self._current_file = story_path
            self._paused = False
            self._is_playing = True
            self._playback_token += 1
            token = self._playback_token
            self._last_position = 0.0

        threading.Thread(target=self._wait_for_story_end, args=(token,), daemon=True).start()
        threading.Thread(target=self._report_playback_progress, args=(token,), daemon=True).start()

    def _wait_for_story_end(self, token: int):
        while True:
            with self._lock:
                if token != self._playback_token:
                    return
                busy = pygame.mixer.music.get_busy()
                paused = self._paused

            if not busy and not paused:
                with self._lock:
                    if token != self._playback_token:
                        return
                    self._is_playing = False
                    self._paused = False
                    self._current_file = None
                    self._last_position = 0.0

                print("[AudioPlayer] Story playback finished.")

                if self._on_story_finished_callback:
                    try:
                        self._on_story_finished_callback()
                    except Exception as exc:
                        print("[AudioPlayer] Error in on_story_finished_callback:", exc)
                return

            time.sleep(0.1)

    def _report_playback_progress(self, token: int):
        """Periodically log playback position using pygame's tracking."""
        while True:
            with self._lock:
                if token != self._playback_token:
                    return
                playing = self._is_playing
                paused = self._paused

            if not playing and not paused:
                return

            pos_ms = pygame.mixer.music.get_pos()
            if pos_ms >= 0:
                status = "paused" if paused else "playing"
                seconds = pos_ms / 1000.0
                with self._lock:
                    if token == self._playback_token:
                        self._last_position = seconds
                print(f"[AudioPlayer] Story {status} time: {seconds:.1f}s")

            time.sleep(1)

    def pause_story(self):
        with self._lock:
            if self._is_playing and not self._paused:
                print("[AudioPlayer] Pausing story.")
                try:
                    pygame.mixer.music.pause()
                    self._paused = True
                except Exception as exc:
                    print("[AudioPlayer] Error while pausing playback:", exc)

    def resume_story(self):
        with self._lock:
            if self._is_playing and self._paused:
                print("[AudioPlayer] Resuming story.")
                try:
                    pygame.mixer.music.unpause()
                    self._paused = False
                except Exception as exc:
                    print("[AudioPlayer] Error while resuming playback:", exc)

    def stop_story(self):
        with self._lock:
            self._stop_story_locked()

    def _stop_story_locked(self):
        if self._is_playing or self._paused:
            print("[AudioPlayer] Stopping story playback.")
        try:
            pygame.mixer.music.stop()
        except Exception as exc:
            print("[AudioPlayer] Error while stopping playback:", exc)
        finally:
            self._playback_token += 1
            self._is_playing = False
            self._paused = False
            self._current_file = None
            self._last_position = 0.0

    def get_playback_position(self) -> float:
        """Return the current playback position in seconds (monotonic, clamped)."""
        with self._lock:
            active = self._is_playing or self._paused
            last_position = self._last_position

        if not active:
            return 0.0

        pos_ms = pygame.mixer.music.get_pos()
        if pos_ms >= 0:
            seconds = pos_ms / 1000.0
            with self._lock:
                if self._is_playing or self._paused:
                    self._last_position = seconds
                    return seconds
        return last_position
