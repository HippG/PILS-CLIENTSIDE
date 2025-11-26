#!/usr/bin/env python3
import time
import threading
import signal
from pathlib import Path
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
from hardware.buttons import StopButton
from hardware.selector import DurationSelector

from services.audio_player import AudioPlayer
from services.led_controller import LedController
from services.story_led_timeline import load_story_led_timeline
from services.system_audio_manager import SystemAudioManager
from services.network_monitor import NetworkMonitor
from services.api_client import StoryApiClient



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
        self._tag_names = {}
        self._tag_colors = {}
        self._generated_story_dir = Path(__file__).resolve().parent / "generated_stories"

        self._reader_to_group = {
            "reader1": 2,
            "reader2": 3,
            "reader3": 1,
            "reader4": 0,
        }
        self._group_highlight_colors = [
            (255, 120, 30),
            (120, 220, 120),
            (80, 160, 255),
            (200, 120, 255),
        ]
        self._reader_active_tags = {reader_id: None for reader_id in self._reader_to_group}

        print(f"[Controller] Initial state: {self.state.name}")
        self.led_controller.apply_state(self.state)

    # ---------- helpers ----------

    def _set_state(self, new_state: StoryBoxState):
        if new_state == self.state:
            return
        print(f"[State] {self.state.name} → {new_state.name}")
        self.state = new_state
        self.led_controller.apply_state(new_state)

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
            self.led_controller.trigger_event("internet_connected")
            time.sleep(4.0)
        if self.state in (StoryBoxState.BOOTING, StoryBoxState.WAITING_NETWORK):
            self._set_state(StoryBoxState.IDLE_READY)
            self.start_preparing()

    def notify_no_internet(self):
        """Trigger when connectivity is lost so we play the associated prompt."""
        self._set_state(StoryBoxState.WAITING_NETWORK)
        print("[Controller] Network unavailable. Waiting for connectivity.")
        self._play_system_prompt("system", "no_internet")

    def start_preparing(self):
        """
        On passe en mode PREPARING_STORY :
        l'enfant peut poser des figurines et choisir la durée.
        """
        self._set_state(StoryBoxState.PREPARING_STORY)
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

        character_name = self._character_name(tag_id)

        if previous != tag_id:
            self._play_system_prompt("characters", character_name)

        self._update_preparing_feedback()

        print(
            f"[Controller] Character {character_name} detected on {reader_id}. "
            f"Active characters={self.session.characters}"
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
        self._update_preparing_feedback()

        character_name = self._tag_names.get(tag_id) or f"char_{tag_id}"

        print(
            f"[Controller] Character {character_name} removed from {reader_id}. "
            f"Active characters={self.session.characters}"
        )

    def _character_name(self, tag_id: int) -> str:
        if tag_id in self._tag_names:
            return self._tag_names[tag_id]

        fallback = f"char_{tag_id}"
        if not self.api_client:
            return fallback

        info = self.api_client.get_character(tag_id)
        if info:
            self._tag_names[tag_id] = info.name
            if info.group_color:
                self._tag_colors[tag_id] = info.group_color
            return info.name

        print(f"[Controller] Using fallback name for tag {tag_id}.")
        return fallback

    def _update_preparing_feedback(self):
        if self.state != StoryBoxState.PREPARING_STORY:
            return

        active_characters = []
        # Update LEDs and rebuild character list using group order for stability.
        ordered_groups = sorted(self._reader_to_group.items(), key=lambda item: item[1])
        for reader_id, group_index in ordered_groups:
            tag_id = self._reader_active_tags.get(reader_id)
            if tag_id is not None:
                color = self._tag_colors.get(tag_id)
                if color is None:
                    color = self._group_highlight_colors[group_index % len(self._group_highlight_colors)]
                self.led_controller.set_group_color(group_index, color)
                active_characters.append(self._character_name(tag_id))
            else:
                self.led_controller.clear_group_color(group_index)

        self.session.characters = active_characters

    def _configure_story_timeline(self, story_path: Path) -> None:
        script_path = story_path.with_name("leds_timing.json")
        timeline = load_story_led_timeline(script_path)
        if timeline:
            print(f"[Controller] Loaded LED timeline from {script_path}")
            self.led_controller.set_story_timeline(timeline, self.audio_player.get_playback_position)
        else:
            if script_path.is_file():
                print(f"[Controller] Invalid LED timeline in {script_path}, using default pattern.")
            else:
                print(f"[Controller] No LED timeline found near {story_path}, using default pattern.")
            self.led_controller.clear_story_timeline()

    def on_duration_change(self, mode: str):
        self.session.duration_mode = mode
        print(f"[Controller] Duration mode changed to: {mode}")
        self._play_system_prompt("system", mode)

    def on_rotary_rotate(self, delta: int):
        # Gestion volume
        new_volume = self.audio_output.volume + delta * 0.015
        self.audio_output.set_volume(new_volume)

    def on_rotary_click(self):
        print(f"[Controller] Rotary click received in state={self.state.name}")
        self.led_controller.trigger_event("play_button_press")
        if self.state == StoryBoxState.PREPARING_STORY:
            self.request_story()
        elif self.state == StoryBoxState.PLAYING_STORY:
            self.pause_story()
        elif self.state == StoryBoxState.PAUSED or self.state == StoryBoxState.CONFIRM_STOP:
            self.resume_story()

        else:
            print("[Controller] Rotary click ignored in this state.")

    def on_stop_button(self):
        print(f"[Controller] Stop button pressed in state={self.state.name}")
        self.led_controller.trigger_event("stop_button_press")
        if self.state in (StoryBoxState.PLAYING_STORY, StoryBoxState.PAUSED):
            if not self._pending_stop_confirm:
                self._pending_stop_confirm = True
                self.pause_story()
                self._set_state(StoryBoxState.CONFIRM_STOP)
                self._play_system_prompt("system", "stop_story")
                print("[Controller] Asking for confirmation to stop story. Press stop again to confirm.")
            else:
                print("[Controller] Stop confirmed. Ending story.")
                self.stop_story_and_reset()
        elif self.state == StoryBoxState.CONFIRM_STOP:
            print("[Controller] Stop confirmed. Ending story.")
            self.stop_story_and_reset()
        else:
            self._play_system_prompt("system", "stop_button_explain")
            print("[Controller] Stop button ignored in this state.")

    # ---------- logique métier ----------

    def request_story(self):
        """
        Pour la maquette : on ignore l'API et on joue directement epic.mp3
        après un petit délai simulé.
        """
        if self.state != StoryBoxState.PREPARING_STORY:
            print("[Controller] request_story() called in invalid state.")
            return

        if not self.session.characters:
            print("[Controller] Cannot request story without characters.")
            self._play_system_prompt("system", "no_characters")
            return

        self._set_state(StoryBoxState.REQUESTING_STORY)
        print(
            f"[Controller] Requesting story for characters={self.session.characters} "
            f"with duration={self.session.duration_mode}."
        )

        def run():
            self._play_system_prompt("system", "story_waiting")
            story_path = None
            if self.api_client:
                story_path = self.api_client.generate_story(
                    duration=self.session.duration_mode,
                    characters=self.session.characters,
                    output_dir=self._generated_story_dir,
                )
            else:
                print("[Controller] No API client configured, unable to request story.")

            if not story_path:
                print("[Controller] Story request failed.")
                if self.story_file:
                    print("[Controller] Falling back to default story file.")
                    self._play_system_prompt("system", "story_start")
                    self.session.story_audio_path = self.story_file
                    print(f"[Controller] Story ready: {self.session.story_audio_path}")
                    self.start_story()
                else:
                    self._play_system_prompt("system", "error")
                    self._set_state(StoryBoxState.PREPARING_STORY)
                    self._update_preparing_feedback()
                return

            self._play_system_prompt("system", "story_start")
            time.sleep(5.0)
            self.session.story_audio_path = str(story_path)
            print(f"[Controller] Story ready: {self.session.story_audio_path}")
            self.start_story()

        threading.Thread(target=run, daemon=True).start()

    def start_story(self):
        if not self.session.story_audio_path:
            print("[Controller] No story file set, cannot start.")
            return

        story_path = Path(self.session.story_audio_path).expanduser()
        self._configure_story_timeline(story_path)
        self._set_state(StoryBoxState.PLAYING_STORY)
        print("[Controller] Starting story playback.")
        self._pending_stop_confirm = False

        # Lancer audio + LEDs
        self.audio_player.play_story(str(story_path))

    def pause_story(self):
        if self.state != StoryBoxState.PLAYING_STORY:
            print("[Controller] Cannot pause, story not playing.")
            return

        self._set_state(StoryBoxState.PAUSED)
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
        self.led_controller.clear_story_timeline()
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
        self.led_controller.clear_story_timeline()
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
    stop_button = None
    selector = None
    api_client = StoryApiClient()

    try:
        # Audio player (avec callback sur fin d'histoire)
        audio_player = AudioPlayer(on_story_finished_callback=lambda: controller.on_story_finished())

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

        # Bouton stop sur GPIO 23
        stop_button = StopButton(
            pin=23,
            on_press=controller.on_stop_button
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
        stop_button.start()
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
        if stop_button:
            stop_button.stop()
        if selector:
            selector.stop()

        if led_controller:
            led_controller.shutdown()
        print("[Main] Cleaning up GPIO.")
        GPIO.cleanup()


if __name__ == "__main__":
    main()
