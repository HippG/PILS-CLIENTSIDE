import threading
import time
from typing import Callable, Optional

from domain.states import StoryBoxState

from .led_patterns import PATTERN_FACTORIES, LedPattern, ScriptedTimelinePattern
from .story_led_timeline import StoryLedTimeline


STATE_PATTERN_MAP = {
    StoryBoxState.BOOTING: "loading_blue_cycle",
    StoryBoxState.WAITING_NETWORK: "loading_blue_cycle",
    StoryBoxState.REQUESTING_STORY: "loading_blue_cycle",
    StoryBoxState.PREPARING_STORY: "preparing_group_cycle",
    StoryBoxState.PLAYING_STORY: "story_pulse",
}

EVENT_PATTERN_MAP = {
    "play_button_press": "flash_play_button",
    "stop_button_press": "flash_stop_button",
    "internet_connected": "flash_internet_connected",
}


class LedController:
    """Coordinates LED patterns for states and transient events."""

    _FRAME_INTERVAL = 1.0 / 40.0

    def __init__(self, led_driver):
        self.led_driver = led_driver
        self._pixel_count = getattr(led_driver, "led_count", 0)

        self._state_pattern_id: Optional[str] = None
        self._state_pattern: Optional[LedPattern] = None

        self._event_pattern_id: Optional[str] = None
        self._event_pattern: Optional[LedPattern] = None

        self._current_state: Optional[StoryBoxState] = None
        self._story_timeline: Optional[StoryLedTimeline] = None
        self._story_time_supplier: Optional[Callable[[], float]] = None

        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._strip_active = False
        self._loop_thread.start()

    def apply_state(self, state: StoryBoxState) -> None:
        with self._lock:
            self._current_state = state
            self._apply_current_state_locked()

    def trigger_event(self, event_name: str) -> None:
        pattern_id = EVENT_PATTERN_MAP.get(event_name)
        if not pattern_id:
            return
        with self._lock:
            self._event_pattern_id = pattern_id
            self._event_pattern = self._instantiate_pattern(pattern_id)

    def set_group_color(self, group_index: int, color) -> None:
        with self._lock:
            pattern = self._state_pattern
            if pattern and hasattr(pattern, "set_group_color"):
                try:
                    pattern.set_group_color(group_index, color)
                except Exception as exc:
                    print(f"[LedController] Failed to set group color: {exc}")

    def clear_group_color(self, group_index: int) -> None:
        with self._lock:
            pattern = self._state_pattern
            if pattern and hasattr(pattern, "clear_group_color"):
                try:
                    pattern.clear_group_color(group_index)
                except Exception as exc:
                    print(f"[LedController] Failed to clear group color: {exc}")

    def clear_all_group_colors(self) -> None:
        with self._lock:
            pattern = self._state_pattern
            if pattern and hasattr(pattern, "clear_all_group_colors"):
                try:
                    pattern.clear_all_group_colors()
                except Exception as exc:
                    print(f"[LedController] Failed to clear all group colors: {exc}")

    def clear(self) -> None:
        with self._lock:
            self._state_pattern_id = None
            self._state_pattern = None
            self._event_pattern_id = None
            self._event_pattern = None
        self.led_driver.off()

    def set_story_timeline(
        self,
        timeline: Optional[StoryLedTimeline],
        time_supplier: Optional[Callable[[], float]],
    ) -> None:
        with self._lock:
            self._story_timeline = timeline
            self._story_time_supplier = time_supplier
            if self._current_state == StoryBoxState.PLAYING_STORY:
                self._apply_current_state_locked()

    def clear_story_timeline(self) -> None:
        self.set_story_timeline(None, None)

    def shutdown(self) -> None:
        self._stop_event.set()
        self._loop_thread.join(timeout=1.5)
        self.led_driver.off()

    def _instantiate_pattern(self, pattern_id: Optional[str]) -> Optional[LedPattern]:
        if not pattern_id:
            return None
        factory = PATTERN_FACTORIES.get(pattern_id)
        if not factory:
            print(f"[LedController] Warning: pattern '{pattern_id}' not found.")
            return None
        pattern = factory()
        pattern.reset(self._pixel_count)
        return pattern

    def _instantiate_story_pattern_locked(self) -> Optional[LedPattern]:
        if not self._story_timeline or not self._story_time_supplier:
            return None
        try:
            pattern = ScriptedTimelinePattern(self._story_timeline, self._story_time_supplier)
        except Exception as exc:
            print(f"[LedController] Failed to create scripted pattern: {exc}")
            return None
        pattern.reset(self._pixel_count)
        return pattern

    def _apply_current_state_locked(self) -> None:
        if self._current_state is None:
            self._state_pattern_id = None
            self._state_pattern = None
            return

        if (
            self._current_state == StoryBoxState.PLAYING_STORY
            and self._story_timeline is not None
            and self._story_time_supplier is not None
        ):
            self._state_pattern_id = None
            pattern = self._instantiate_story_pattern_locked()
            if pattern is None:
                fallback_id = STATE_PATTERN_MAP.get(StoryBoxState.PLAYING_STORY)
                self._state_pattern_id = fallback_id
                self._state_pattern = self._instantiate_pattern(fallback_id)
            else:
                self._state_pattern = pattern
        else:
            pattern_id = STATE_PATTERN_MAP.get(self._current_state)
            self._state_pattern_id = pattern_id
            self._state_pattern = self._instantiate_pattern(pattern_id)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            colors = None
            had_pattern = False

            with self._lock:
                if self._event_pattern and self._event_pattern_id:
                    current_pattern = self._event_pattern
                else:
                    current_pattern = self._state_pattern

                if current_pattern:
                    had_pattern = True
                    try:
                        colors = current_pattern.render()
                    except Exception as exc:  # pragma: no cover - defensive logging
                        print(f"[LedController] Error while rendering pattern: {exc}")
                        colors = []

                    if self._event_pattern and self._event_pattern.is_finished():
                        self._event_pattern = None
                        self._event_pattern_id = None
                    elif self._state_pattern and self._state_pattern.is_finished():
                        self._state_pattern = self._instantiate_pattern(self._state_pattern_id)

            if had_pattern and colors is not None:
                if len(colors) == self._pixel_count:
                    self.led_driver.set_pixels(colors)
                    self._strip_active = True
                else:
                    if colors:
                        print("[LedController] Warning: pattern rendered unexpected color count; turning off LEDs.")
                    self.led_driver.off()
                    self._strip_active = False
            else:
                if self._strip_active:
                    self.led_driver.off()
                    self._strip_active = False

            time.sleep(self._FRAME_INTERVAL)

        # Ensure LEDs are off when stopping the loop.
        self.led_driver.off()
        self._strip_active = False
