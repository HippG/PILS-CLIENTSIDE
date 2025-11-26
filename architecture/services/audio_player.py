import atexit
import threading
import time
import json
from pathlib import Path
from typing import Optional
import pygame

from services.led_patterns import *

# Association entre le nom du pattern (dans le JSON) et la classe Python
PATTERN_MAP = {
    "cycle": CyclePattern, #argument color obligatoire
    "fill": FillPattern, #argument color obligatoire
    "breathe_slow": BreatheSlowPattern, #argument color obligatoire
    "breathe_fast": BreatheFastPattern, #argument color obligatoire
    "fire": FirePattern, #pas de couleur
    "cornerblast": CornerBlastPattern, #argument color obligatoire
    "rain": RainPattern, #pas de couleur
    "flash": FlashPattern, #argument color obligatoire
    "sparkle": SparklePattern, #argument color obligatoire
}


class AudioPlayer:
    """Lecture d'histoires longues avec pygame.mixer.music et synchronisation LED."""

    def __init__(self, on_story_finished_callback=None, led_controller=None):
        self._lock = threading.Lock()
        self._paused = False
        self._is_playing = False
        self._current_file: Optional[Path] = None
        self._playback_token = 0
        self._on_story_finished_callback = on_story_finished_callback
        self._led_controller = led_controller

        if not pygame.mixer.get_init():
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
            print("[AudioPlayer] pygame.mixer initialized.")

        atexit.register(self.stop_story)

    # ---------- Lecture principale ----------

    def play_story(self, filepath: str, led_json_path: Optional[str] = None):
        """
        Lance la lecture de l'histoire (non bloquant).
        Peut aussi lancer la synchronisation LED à partir d'un fichier JSON fourni.
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

        # Threads parallèles
        threading.Thread(target=self._wait_for_story_end, args=(token,), daemon=True).start()
        threading.Thread(
            target=self._sync_led_patterns_with_audio,
            args=(token, led_json_path),
            daemon=True
        ).start()

    # ---------- Fin automatique ----------

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

                print("[AudioPlayer] Story playback finished.")

                if self._on_story_finished_callback:
                    try:
                        self._on_story_finished_callback()
                    except Exception as exc:
                        print("[AudioPlayer] Error in on_story_finished_callback:", exc)
                return

            time.sleep(0.1)


    # ---------- Synchronisation LED ----------

    def _sync_led_patterns_with_audio(self, token: int, led_json_path: Optional[str]):
        """
        Lit le fichier led_timings.json (ou autre) et applique les motifs LED
        selon le temps de lecture audio.
        """
        if not self._led_controller:
            print("[AudioPlayer] No LED controller provided; skipping LED sync.")
            return

        if led_json_path:
            led_timing_path = Path(led_json_path).expanduser().resolve()
        else:
            led_timing_path = Path(__file__).resolve().parent / "led_timings.json"

        if not led_timing_path.is_file():
            print(f"[AudioPlayer] WARNING: {led_timing_path} not found.")
            return

        try:
            with open(led_timing_path, "r") as f:
                data = json.load(f)
                timings = data.get("audio_led_sync", [])
        except Exception as exc:
            print(f"[AudioPlayer] Error reading {led_timing_path.name}: {exc}")
            return

        if not timings:
            print(f"[AudioPlayer] No LED timings found in {led_timing_path.name}.")
            return

        timings.sort(key=lambda e: e.get("start_time", 0))
        current_pattern = None
        print(f"[AudioPlayer] Loaded {len(timings)} LED sync events from {led_timing_path.name}.")

        while True:
            with self._lock:
                if token != self._playback_token:
                    return
                if not self._is_playing:
                    break
                if self._paused:
                    time.sleep(0.1)
                    continue

            pos_ms = pygame.mixer.music.get_pos()
            if pos_ms < 0:
                time.sleep(0.1)
                continue

            current_time = pos_ms / 1000.0  # secondes

            # Trouve la section active
            active_event = None
            for event in timings:
                if event["start_time"] <= current_time < event["end_time"]:
                    active_event = event
                    break

            # Applique le motif si changement
            if active_event:
                if active_event != current_pattern:
                    pattern_name = active_event.get("pattern")
                    color = active_event.get("color", None)
                    pattern_class = PATTERN_MAP.get(pattern_name)

                    if pattern_class:
                        print(f"[AudioPlayer] LED pattern → {pattern_name} at {current_time:.1f}s")
                        try:
                            if color:
                                self._led_controller.set_background_pattern(
                                    pattern_class,
                                    color=(color["r"], color["g"], color["b"])
                                )
                            else:
                                self._led_controller.set_background_pattern(
                                    pattern_class
                                )
                        except Exception as exc:
                            print(f"[AudioPlayer] LED pattern error: {exc}")
                    else:
                        print(f"[AudioPlayer] Unknown LED pattern '{pattern_name}'")

                    current_pattern = active_event

            time.sleep(0.1)

    # ---------- Contrôles de lecture ----------

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
