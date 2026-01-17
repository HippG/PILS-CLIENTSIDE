#!/usr/bin/env python3
import time
import threading
import signal
from pathlib import Path
from typing import Dict, Optional, List
import RPi.GPIO as GPIO
import warnings
import os

os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"   # hides "Hello from the pygame community"
warnings.filterwarnings("ignore", category=RuntimeWarning, module="importlib._bootstrap")


from domain.states import StoryBoxState
from domain.story_session import StorySession

from hardware.audio_output import AudioOutput
from hardware.leds import LedDriver
from hardware.rfid_reader import RFIDReaderManager
from hardware.rotary_encoder import RotaryEncoder
from hardware.buttons import PlayPauseButton
from hardware.selector import DurationSelector

from services.audio_player import AudioPlayer
from services.led_controller import LedController
from services.led_patterns import *
from services.system_audio_manager import SystemAudioManager
from services.network_monitor import NetworkMonitor
from services.api_client import StoryApiClient, CharacterInfo



class StoryBoxController:
    """
    Contrôleur principal : gère les états et les réactions aux événements hardware.
    """
    def __init__(
        self,
        story_file: str,
        audio_player: AudioPlayer,
        led_controller: LedController,
        audio_output: AudioOutput,
        system_audio: SystemAudioManager,
        api_client: StoryApiClient,
    ):
        self.story_file = story_file
        self.audio_player = audio_player
        self.led_controller = led_controller
        self.audio_output = audio_output
        self.system_audio = system_audio
        self.api_client = api_client

        self.state = StoryBoxState.BOOTING
        self.session = StorySession()
        self._pending_stop_confirm = False
        self._duration_selector = None
        self._generated_story_dir = Path(__file__).resolve().parent / "generated_stories"

        self._reader_to_group = {
            "reader1": 2,
            "reader2": 3,
            "reader3": 1,
            "reader4": 0,
        }
        self._group_highlight_colors = [
            (255, 0, 0),
            (255, 0, 0),
            (255, 0, 0),
            (255, 0, 0),
        ]
        self._reader_active_tags = {reader_id: None for reader_id in self._reader_to_group}

        self.loading_stop_event = threading.Event()

        print(f"[Controller] Initial state: {self.state.name}")

    # ---------- helpers ----------

    def _set_state(self, new_state: StoryBoxState):
        if new_state == self.state:
            return
        print(f"[State] {self.state.name} → {new_state.name}")
        self.state = new_state

    def _play_system_prompt(self, category: str, event_name: str) -> None:
        """Play a short prompt only if a story is not currently playing."""
        if self.state == StoryBoxState.PLAYING_STORY:
            self.system_audio.play_event("system", "error")
            return
        self.system_audio.play_event(category, event_name)

    def attach_duration_selector(self, selector: DurationSelector):
        """Keep a reference to the selector so we can resync after resets."""
        self._duration_selector = selector

    def get_state(self) -> StoryBoxState:
        return self.state

    # ---------- lifecycle ----------

    def on_network_ready(self):
        print("[Controller] Network available.")
        if self.state == StoryBoxState.WAITING_NETWORK:
            self._play_system_prompt("system", "internet_connected")
            self.led_controller.led_event(
                InstantFlashPattern,
                color=(0, 255, 0),
                duration=4.0,
            )
            time.sleep(4.0)
        if self.state in (StoryBoxState.BOOTING, StoryBoxState.WAITING_NETWORK):
            self._set_state(StoryBoxState.IDLE_READY)
            self.start_preparing()

    def notify_no_internet(self):
        """Trigger when connectivity is lost so we play the associated prompt."""
        self._set_state(StoryBoxState.WAITING_NETWORK)
        print("[Controller] Network unavailable. Waiting for connectivity.")
        self.led_controller.set_background_pattern(
            CyclePattern,
            color=(0, 255, 255),
            background=(0, 0, 0),
            speed=5.0,
            tail=10,
        )
        self._play_system_prompt("system", "no_internet")

    def start_preparing(self):

        self._set_state(StoryBoxState.PREPARING_STORY)
        self.led_controller.set_background_pattern(
            GroupCyclePattern,
            group_lengths=[6, 8, 8, 8],
            background_palette=[
            (163, 131, 13),
            (222, 97, 31),
        ]
        )

        self.session.duration_mode = self._duration_selector.read_mode()
        print("[Controller] Preparing story: place figurines and choose duration.")
        print(f"[Controller] Current duration mode = {self.session.duration_mode}")
        self._play_system_prompt("system", "preparing_story")
        self._update_preparing_feedback()

    # ---------- callbacks hardware ----------

    def on_tag_detected(self, reader_id: str, tag_id: int):

        if reader_id not in self._reader_active_tags:
            print(f"[Controller] Unknown RFID reader '{reader_id}', ignoring tag {tag_id}.")
            return

        previous = self._reader_active_tags.get(reader_id)
        self._reader_active_tags[reader_id] = tag_id

        if self.state != StoryBoxState.PREPARING_STORY:
            print(
                f"[Controller] Tag {tag_id} detected on {reader_id} while state={self.state.name}. "
                "Stored for later."
            )
            return

        character_info = self._fetch_character_info(tag_id)
        character_name = character_info.name

        if previous != tag_id:
            self._play_system_prompt("characters", character_name)

        active_names = self._update_preparing_feedback(prefetched_info={tag_id: character_info})

        print(
            f"[Controller] Character {character_name} detected on {reader_id}. "
            f"Active figure_uids={self.session.figure_rfid_uids}; names={active_names}"
        )

    def on_tag_removed(self, reader_id: str):
        if reader_id not in self._reader_active_tags:
            print(f"[Controller] Unknown RFID reader '{reader_id}' removal event ignored.")
            return

        tag_id = self._reader_active_tags.get(reader_id)
        if tag_id is None:
            return

        self._reader_active_tags[reader_id] = None

        if self.state != StoryBoxState.PREPARING_STORY:
            print(f"[Controller] Tag {tag_id} removed from {reader_id} while state={self.state.name}.")
            return

        self._play_system_prompt("system", "tag_removed")
        removed_info = self._fetch_character_info(tag_id)
        active_names = self._update_preparing_feedback()

        print(
            f"[Controller] Character {removed_info.name} removed from {reader_id}. "
            f"Active figure_uids={self.session.figure_rfid_uids}; names={active_names}"
        )

    def _fetch_character_info(self, tag_id: int) -> CharacterInfo:
        fallback_info = CharacterInfo(name=f"char_{tag_id}")
        if not self.api_client:
            return fallback_info

        info = self.api_client.get_character(tag_id)
        if info:
            return info

        print(f"[Controller] Using fallback character info for tag {tag_id}.")
        return fallback_info

    def _update_preparing_feedback(
        self,
        prefetched_info: Optional[Dict[int, CharacterInfo]] = None,
    ) -> List[str]:
        if self.state != StoryBoxState.PREPARING_STORY:
            return []

        active_tag_ids = []
        active_names = []
        ordered_groups = sorted(self._reader_to_group.items(), key=lambda item: item[1])
        for reader_id, group_index in ordered_groups:
            tag_id = self._reader_active_tags.get(reader_id)
            if tag_id is not None:
                info = None
                if prefetched_info:
                    info = prefetched_info.get(tag_id)
                if info is None:
                    info = self._fetch_character_info(tag_id)
                color = info.group_color or self._group_highlight_colors[group_index % len(self._group_highlight_colors)]
                self.led_controller.set_group_color(group_index, color)
                active_tag_ids.append(tag_id)
                active_names.append(info.name)
            else:
                self.led_controller.clear_group_color(group_index)

        self.session.figure_rfid_uids = active_tag_ids
        return active_names

    def on_duration_change(self, mode: str):
        self.session.duration_mode = mode
        print(f"[Controller] Duration mode changed to: {mode}")

        self._play_system_prompt("system", str(mode))

    def on_rotary_rotate(self, delta: int):
        # Gestion volume
        new_volume = self.audio_output.volume + delta * 0.015
        self.audio_output.set_volume(new_volume)

    def on_rotary_click(self):
        print(f"[Controller] Rotary click received but UNUSED in this version.")
        # User requested to disable rotary button click functionality.
        pass

    def on_play_pause_click(self):
        print(f"[Controller] Play/Pause button clicked in state={self.state.name}")
        self.led_controller.led_event(InstantFlashPattern, color=(255, 0, 0), duration=1.0)

        if self.state == StoryBoxState.PREPARING_STORY:
            self.request_story()
        
        elif self.state == StoryBoxState.PLAYING_STORY:
            # "PAUSE state doesnt exist anymore, we directly play the stop_story audio"
            # Pause actual audio playback
            self.audio_player.pause_story()
            # Go directly to CONFIRM_STOP
            self._set_state(StoryBoxState.CONFIRM_STOP)
            self._play_system_prompt("system", "stop_story")
            self.led_controller.led_event(BreatheSlowPattern, color=(255, 0, 0))
            print("[Controller] Story paused -> Confirm Stop state.")

        elif self.state == StoryBoxState.CONFIRM_STOP:
            # Resume story
            self.resume_story()

        else:
            print("[Controller] Play/Pause click ignored in this state.")

    def on_play_pause_long_press(self):
        print(f"[Controller] Play/Pause button LONG PRESSED in state={self.state.name}")
        
        # Only relevant if we are in CONFIRM_STOP state (or maybe PLAYING if user holds it directly?)
        # User said: "If long pressed (+5secs) in the CONFIRM STOP state : stop_story_and_reset."
        if self.state == StoryBoxState.CONFIRM_STOP:
            self.stop_story_and_reset()
        else:
            print("[Controller] Long press ignored in this state.")

    # ---------- logique métier ----------

    def request_story(self):
        """
        Pour la maquette : on ignore l'API et on joue directement epic.mp3
        après un petit délai simulé.
        """
        if self.state != StoryBoxState.PREPARING_STORY:
            print("[Controller] request_story() called in invalid state.")
            return

        if not self.session.figure_rfid_uids:
            print("[Controller] Cannot request story without figures.")
            self._play_system_prompt("system", "no_characters")
            return

        self._set_state(StoryBoxState.REQUESTING_STORY)
        self.led_controller.set_background_pattern(
            CyclePattern,
            color=(0, 255, 255),
            background=(0, 0, 0),
            speed=5.0,
            tail=10,
        )
        print(
            f"[Controller] Requesting story for figure_uids={self.session.figure_rfid_uids} "
            f"with duration={self.session.duration_mode}."
        )

        def run():
            self.loading_stop_event.clear()
            threading.Thread(target=self._play_loading_loop, daemon=True).start()
            story_assets = None
            if self.api_client:
                story_assets = self.api_client.generate_story(
                    duration=self.session.duration_mode,
                    figure_rfid_uids=self.session.figure_rfid_uids,
                    output_dir=self._generated_story_dir,
                )
            else:
                print("[Controller] No API client configured, unable to request story.")

            if not story_assets:
                print("[Controller] Story request failed.")
                if self.story_file:
                    print("[Controller] Falling back to default story file.")
                    self._play_system_prompt("system", "story_start")
                    self.session.story_audio_path = self.story_file
                    default_led_path = self._generated_story_dir / "leds_timing.json"
                    self.session.led_pattern_path = (
                        str(default_led_path)
                        if default_led_path.exists()
                        else None
                    )
                    print(f"[Controller] Story ready: {self.session.story_audio_path}")
                    self.start_story()
                else:
                    self._play_system_prompt("system", "error")
                    self._set_state(StoryBoxState.PREPARING_STORY)
                    self._update_preparing_feedback()
                return
            
            self.loading_stop_event.set()
            self._play_system_prompt("system", "story_start")
            time.sleep(5.0)
            self.session.story_audio_path = str(story_assets.audio_path)
            self.session.led_pattern_path = str(story_assets.led_pattern_path)
            print(
                f"[Controller] Story ready: {self.session.story_audio_path} "
                f"with LEDs {self.session.led_pattern_path}"
            )

            self.start_story()

        threading.Thread(target=run, daemon=True).start()

    def _play_loading_loop(self):
        while not self.loading_stop_event.is_set():
            self._play_system_prompt("system", "story_waiting")
            time.sleep(random.uniform(12,15))
        return

    def start_story(self):
        if not self.session.story_audio_path:
            print("[Controller] No story file set, cannot start.")
            return

        self._set_state(StoryBoxState.PLAYING_STORY)
        print("[Controller] Starting story playback.")
        self._pending_stop_confirm = False

        # Lancer audio + LEDs
        self.audio_player.play_story(
            self.session.story_audio_path,
            self.session.led_pattern_path,
        )

    def pause_story(self):
        if self.state != StoryBoxState.PLAYING_STORY:
            print("[Controller] Cannot pause, story not playing.")
            return

        self._set_state(StoryBoxState.PAUSED)
        self.led_controller.led_event(
            BreatheSlowPattern,
            color=(0, 0, 255),
        )
        self.audio_player.pause_story()
        print("[Controller] Story paused.")

    def resume_story(self):
        if (self.state != StoryBoxState.PAUSED) and (self.state != StoryBoxState.CONFIRM_STOP):
            print("[Controller] Cannot resume, story not paused.")
            return
        
        self._pending_stop_confirm = False
        self._set_state(StoryBoxState.PLAYING_STORY)
        self.audio_player.resume_story()
        print("[Controller] Story resumed.")

    def stop_story_and_reset(self):
        print("[Controller] Stopping story and resetting session.")
        self.audio_player.stop_story()
        self.session = StorySession()
        self.session.duration_mode = self._duration_selector.read_mode()
        self._pending_stop_confirm = False
        self._set_state(StoryBoxState.IDLE_READY)
        self.start_preparing()

    def on_story_finished(self):
        """
        Callback appelé par AudioPlayer quand l'histoire est terminée.
        """
        print("[Controller] Story finished naturally.")
        self.session = StorySession()
        self.session.duration_mode = self._duration_selector.read_mode()
        self._pending_stop_confirm = False
        self._set_state(StoryBoxState.IDLE_READY)
        self.start_preparing()


def main():
    GPIO.setmode(GPIO.BCM)

    shutdown_event = threading.Event()

    def handle_shutdown(signum=None, _frame=None):
        """Signal handler to request an orderly shutdown."""
        reason = f"Signal {signum} received" if signum is not None else "Shutdown requested"
        if not shutdown_event.is_set():
            print(f"\n[Main] {reason}, shutting down...")
        shutdown_event.set()

    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)

    story_file = "epic.mp3"  # adapte le chemin si besoin
    

    system_audio_manager = SystemAudioManager(
        base_directory=Path(__file__).resolve().parent / "audios",
    )

    audio_output = AudioOutput()
    led_driver = LedDriver()
    led_controller = LedController(led_driver)

    controller = None
    audio_player = None
    network_monitor = None
    rfid_manager = None
    rotary = None
    play_pause_button = None
    selector = None
    api_client = StoryApiClient()

    try:

        audio_player = AudioPlayer(
            on_story_finished_callback=lambda: controller.on_story_finished(),
            led_controller=led_controller
        )

        controller = StoryBoxController(
            story_file=story_file,
            audio_player=audio_player,
            led_controller=led_controller,
            audio_output=audio_output,
            system_audio=system_audio_manager,
            api_client=api_client,
        )

        # --- Hardware ---

        rfid_readers = [
            ("reader1", 5),
            ("reader2", 6),
            ("reader3", 26),
            ("reader4", 12),
        ]
        rfid_manager = RFIDReaderManager(
            readers=rfid_readers,
            on_tag_detected=controller.on_tag_detected,
            on_tag_removed=controller.on_tag_removed,
        )

        # Encodeur rotatif KY-040
        rotary = RotaryEncoder(
            clk_pin=4,
            dt_pin=22,
            sw_pin=17,
            on_click=controller.on_rotary_click,
            on_rotate=controller.on_rotary_rotate
        )

        # Bouton Play/Pause sur GPIO 23 (Anciennement StopButton)
        play_pause_button = PlayPauseButton(
            pin=23,
            on_short_press=controller.on_play_pause_click,
            on_long_press=controller.on_play_pause_long_press,
            long_press_duration=5.0
        )

        # Sélecteur 3 positions sur GPIO 24 / 25
        selector = DurationSelector(
            sw1_pin=24,
            sw2_pin=25,
            on_duration_change=controller.on_duration_change
        )
        controller.attach_duration_selector(selector)

        # Démarrage des threads hardware
        rfid_manager.start()
        rotary.start()
        play_pause_button.start()
        selector.start()

        skip_states = {
            StoryBoxState.PLAYING_STORY,
            StoryBoxState.PAUSED,
            StoryBoxState.CONFIRM_STOP,
        }

        network_monitor = NetworkMonitor(
            state_provider=controller.get_state,
            on_online=controller.on_network_ready,
            on_offline=controller.notify_no_internet,
            interval=10.0,
            skip_states=skip_states,
        )
        network_monitor.start()

        print("[Main] StoryBox running. Press Ctrl+C to exit.")

        while not shutdown_event.is_set():
            time.sleep(1.0)

    except KeyboardInterrupt:
        handle_shutdown()

    finally:
        shutdown_event.set()
        if network_monitor:
            network_monitor.stop()
        if rfid_manager:
            rfid_manager.stop()
        if rotary:
            rotary.stop()
        if play_pause_button:
            play_pause_button.stop()
        if selector:
            selector.stop()

        if led_controller:
            led_controller.shutdown()
        print("[Main] Cleaning up GPIO.")
        GPIO.cleanup()


if __name__ == "__main__":
    main()
