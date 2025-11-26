import atexit
import random
import threading
from pathlib import Path
from typing import Optional

import pygame


class SystemAudioManager:
    """Manage short system prompts using pygame.mixer (low-latency and reliable)."""

    _SUPPORTED_EXTENSIONS = (".mp3", ".wav", ".ogg")

    def __init__(self, base_directory: Path) -> None:
        self._base_directory = Path(base_directory).resolve()
        self._lock = threading.Lock()
        self._is_playing = False
        self._current_sound: Optional[pygame.mixer.Sound] = None
        self._current_channel: Optional[pygame.mixer.Channel] = None

        if not self._base_directory.exists():
            raise ValueError(f"Audio prompts directory does not exist: {self._base_directory}")

        # Initialize pygame mixer once globally
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
        print("[SystemAudio] pygame.mixer initialized.")

        atexit.register(self.close)

    # ---------- Public methods ----------

    def play_event(self, category: str, event_name: str) -> None:
        """
        Play the audio prompt associated with *event_name* under *category*.
        Interrupts any currently playing sound.
        """
        folder = self._resolve_event_folder(category, event_name)
        if folder is None:
            print(f"[SystemAudio] No folder for category '{category}', event '{event_name}'.")
            return

        audio_file = self._pick_random_audio(folder)
        if audio_file is None:
            print(f"[SystemAudio] No audio files found in {folder}.")
            return

        with self._lock:
            self._stop_locked()
            try:
                self._current_sound = pygame.mixer.Sound(str(audio_file))
                self._current_channel = self._current_sound.play()
                self._is_playing = True
                print(f"[SystemAudio] Playing prompt: {audio_file}")
            except Exception as exc:
                print(f"[SystemAudio] ERROR: Failed to play sound: {exc}")
                self._is_playing = False

            # Start a watcher thread so we know when playback ends
            threading.Thread(target=self._wait_for_completion, daemon=True).start()

    def stop(self) -> None:
        """Stop current playback immediately."""
        with self._lock:
            self._stop_locked()

    def close(self) -> None:
        """Gracefully stop any sound and quit pygame.mixer."""
        with self._lock:
            self._stop_locked()
        try:
            pygame.mixer.quit()
            print("[SystemAudio] pygame.mixer closed.")
        except Exception:
            pass

    # ---------- Internal helpers ----------

    def _resolve_event_folder(self, category: str, event_name: str) -> Optional[Path]:
        folder = (self._base_directory / category / event_name).resolve()
        if not folder.is_dir():
            return None
        if self._base_directory not in folder.parents:
            return None
        return folder

    def _pick_random_audio(self, folder: Path) -> Optional[Path]:
        files = [
            f for f in folder.iterdir()
            if f.suffix.lower() in self._SUPPORTED_EXTENSIONS and f.is_file()
        ]
        if not files:
            return None
        return random.choice(files)

    def _stop_locked(self) -> None:
        if self._current_channel and self._current_channel.get_busy():
            self._current_channel.stop()
            print("[SystemAudio] Stopped current prompt.")
        self._is_playing = False
        self._current_channel = None
        self._current_sound = None

    def _wait_for_completion(self) -> None:
        """Wait until the sound finishes playing, then clear flags."""
        while True:
            with self._lock:
                if not self._current_channel:
                    break
                busy = self._current_channel.get_busy()
            if not busy:
                with self._lock:
                    self._is_playing = False
                    self._current_channel = None
                    self._current_sound = None
                print("[SystemAudio] Prompt playback finished.")
                break
            pygame.time.wait(50)
