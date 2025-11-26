from __future__ import annotations

import math
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from .story_led_timeline import StoryLedSegment, StoryLedTimeline

Color = Tuple[int, int, int]
PatternFactory = Callable[[], "LedPattern"]


def _clamp(value: float) -> int:
    return max(0, min(255, int(round(value))))


def _scale(color: Color, factor: float) -> Color:
    r, g, b = color
    return (_clamp(r * factor), _clamp(g * factor), _clamp(b * factor))


def _lerp(a: Color, b: Color, t: float) -> Color:
    t = max(0.0, min(1.0, t))
    return (
        _clamp(a[0] + (b[0] - a[0]) * t),
        _clamp(a[1] + (b[1] - a[1]) * t),
        _clamp(a[2] + (b[2] - a[2]) * t),
    )


def _wrap_distance(position: float, index: int, modulo: int) -> float:
    raw = (position - index) % modulo
    return min(raw, modulo - raw)


def _normalize_color(color: Tuple[int, ...]) -> Color:
    components = list(color[:3])
    while len(components) < 3:
        components.append(0)
    return (_clamp(components[0]), _clamp(components[1]), _clamp(components[2]))


def _normalize_palette(palette: Optional[Iterable[Iterable[int]]]) -> Optional[List[Color]]:
    if palette is None:
        return None
    normalized: List[Color] = []
    for entry in palette:
        try:
            normalized.append(_normalize_color(tuple(entry)))
        except TypeError:
            continue
    return normalized or None


class LedPattern:
    """Base class for LED animations."""

    def __init__(self, duration: float | None = None) -> None:
        self._duration = duration
        self._start_time: float | None = None
        self._pixel_count = 0

    def reset(self, pixel_count: int) -> None:
        self._pixel_count = max(0, pixel_count)
        self._start_time = time.monotonic()
        self.on_reset()

    def on_reset(self) -> None:
        """Hook for subclasses to cache data when the pattern restarts."""

    def elapsed(self) -> float:
        if self._start_time is None:
            return 0.0
        return max(0.0, time.monotonic() - self._start_time)

    def is_finished(self) -> bool:
        if self._duration is None:
            return False
        return self.elapsed() >= self._duration

    def render(self) -> List[Color]:
        if self._pixel_count <= 0:
            return []
        return self.render_for_elapsed(self.elapsed())

    def render_for_elapsed(self, elapsed: float) -> List[Color]:
        if self._pixel_count <= 0:
            return []
        safe_elapsed = max(0.0, elapsed)
        return self._render_frame(safe_elapsed, self._pixel_count)

    def _render_frame(self, elapsed: float, pixel_count: int) -> List[Color]:
        raise NotImplementedError


class BlueCyclePattern(LedPattern):
    """Rotating blue comet used for loading states."""

    def __init__(
        self,
        speed_leds_per_sec: float = 10.0,
        tail_length: int = 6,
        highlight: Color = (60, 140, 255),
        background: Color = (0, 0, 12),
    ) -> None:
        super().__init__(duration=None)
        self._speed = speed_leds_per_sec
        self._tail = max(1, tail_length)
        self._highlight = highlight
        self._background = background

    def _render_frame(self, elapsed: float, pixel_count: int) -> List[Color]:
        if pixel_count == 0:
            return []

        head_position = (elapsed * self._speed) % pixel_count
        colors: List[Color] = []
        for idx in range(pixel_count):
            distance = _wrap_distance(head_position, idx, pixel_count)
            intensity = max(0.0, 1.0 - (distance / self._tail))
            colors.append(_lerp(self._background, self._highlight, intensity))
        return colors


class StoryPulsePattern(LedPattern):
    """Multi-color breathing animation for the story playback."""

    def __init__(
        self,
        palette: List[Color] | None = None,
        color_duration: float = 2.5,
        pulse_frequency: float = 0.6,
    ) -> None:
        super().__init__(duration=None)
        self._palette = palette or [
            (255, 100, 40),
            (255, 40, 180),
            (40, 140, 255),
        ]
        self._color_duration = max(0.1, color_duration)
        self._pulse_frequency = pulse_frequency

    def _render_frame(self, elapsed: float, pixel_count: int) -> List[Color]:
        if not self._palette:
            return [(0, 0, 0)] * pixel_count

        cycle_length = self._color_duration * len(self._palette)
        color_position = elapsed % cycle_length
        segment_index = int(color_position / self._color_duration)
        blend_t = (color_position % self._color_duration) / self._color_duration

        base_color = self._palette[segment_index % len(self._palette)]
        next_color = self._palette[(segment_index + 1) % len(self._palette)]
        blended = _lerp(base_color, next_color, blend_t)

        colors: List[Color] = []
        for idx in range(pixel_count):
            offset = (idx / max(1, pixel_count)) * math.pi
            brightness = 0.35 + 0.65 * (0.5 * (1.0 + math.sin((elapsed * self._pulse_frequency * 2 * math.pi) + offset)))
            colors.append(_scale(blended, brightness))
        return colors


class FlashPattern(LedPattern):
    """Short flash used for button feedback."""

    def __init__(self, color: Color, duration: float = 0.35) -> None:
        super().__init__(duration=duration)
        self._color = color

    def _render_frame(self, elapsed: float, pixel_count: int) -> List[Color]:
        if self._duration is None or self._duration <= 0:
            intensity = 0.0
        else:
            progress = min(1.0, elapsed / self._duration)
            intensity = max(0.0, 1.0 - progress)
        scaled = _scale(self._color, intensity)
        return [scaled] * pixel_count


class GroupCyclePattern(LedPattern):
    """Pulsing background that can light up LED groups when requested."""

    def __init__(
        self,
        group_lengths: List[int] | None = None,
        background_palette: Optional[List[Color]] = None,
        background_color_duration: float = 2.5,
        background_pulse_frequency: float = 0.6,
    ) -> None:
        super().__init__(duration=None)
        self._base_lengths = group_lengths or [1]
        self._groups: List[tuple[int, int]] = []
        self._group_overrides: List[Optional[Color]] = []
        self._pixel_group_index: List[int] = []

        self._background_pattern = StoryPulsePattern(
            palette=background_palette,
            color_duration=background_color_duration,
            pulse_frequency=background_pulse_frequency,
        )

    def on_reset(self) -> None:
        total = sum(self._base_lengths)
        if total <= 0 or self._pixel_count <= 0:
            self._groups = []
            self._group_overrides = []
            self._pixel_group_index = []
            self._background_pattern.reset(self._pixel_count)
            return

        scale = self._pixel_count / total
        indices: List[tuple[int, int]] = []
        cursor = 0
        remaining_pixels = self._pixel_count
        remaining_groups = len(self._base_lengths)
        for length in self._base_lengths:
            remaining_groups -= 1
            target = max(1, int(round(length * scale)))
            if remaining_groups == 0:
                target = remaining_pixels
            else:
                target = min(target, remaining_pixels - remaining_groups)
            start = cursor
            stop = min(self._pixel_count, start + target)
            indices.append((start, stop))
            cursor = stop
            remaining_pixels = max(0, self._pixel_count - cursor)

        self._groups = [group for group in indices if group[1] > group[0]]
        self._group_overrides = [None] * len(self._groups)
        self._pixel_group_index = [-1] * self._pixel_count
        for group_index, (start, stop) in enumerate(self._groups):
            for idx in range(start, stop):
                self._pixel_group_index[idx] = group_index

        self._background_pattern.reset(self._pixel_count)

    def set_group_color(self, group_index: int, color: Color) -> None:
        if group_index < 0 or group_index >= len(self._group_overrides):
            return
        self._group_overrides[group_index] = _normalize_color(color)

    def clear_group_color(self, group_index: int) -> None:
        if group_index < 0 or group_index >= len(self._group_overrides):
            return
        self._group_overrides[group_index] = None

    def clear_all_group_colors(self) -> None:
        for idx in range(len(self._group_overrides)):
            self._group_overrides[idx] = None

    def _render_frame(self, elapsed: float, pixel_count: int) -> List[Color]:
        base_colors = self._background_pattern.render()
        if len(base_colors) != pixel_count:
            base_colors = [(0, 0, 0)] * pixel_count
        else:
            base_colors = [_scale(color, 0.1) for color in base_colors]

        colors: List[Color] = []
        for idx in range(pixel_count):
            group_index = -1
            if idx < len(self._pixel_group_index):
                group_index = self._pixel_group_index[idx]

            override = None
            if 0 <= group_index < len(self._group_overrides):
                override = self._group_overrides[group_index]

            if override is not None:
                colors.append(override)
            else:
                colors.append(base_colors[idx])
        return colors


def _build_blue_cycle(params: Dict[str, Any]) -> LedPattern:
    speed = float(params.get("speed_leds_per_sec", params.get("speed", 10.0)))
    tail_length = int(params.get("tail_length", 6))
    highlight = params.get("highlight") or params.get("color")
    background = params.get("background")
    highlight_color = _normalize_color(tuple(highlight)) if highlight else (60, 140, 255)
    background_color = _normalize_color(tuple(background)) if background else (0, 0, 12)
    return BlueCyclePattern(
        speed_leds_per_sec=speed,
        tail_length=tail_length,
        highlight=highlight_color,
        background=background_color,
    )


def _build_story_pulse(params: Dict[str, Any]) -> LedPattern:
    palette = _normalize_palette(params.get("palette") or params.get("colors"))
    color_duration = float(params.get("color_duration", params.get("duration", 2.5)))
    pulse_frequency = float(params.get("pulse_frequency", params.get("frequency", 0.6)))
    return StoryPulsePattern(
        palette=palette,
        color_duration=color_duration,
        pulse_frequency=pulse_frequency,
    )


def _build_flash(params: Dict[str, Any]) -> LedPattern:
    color = params.get("color") or params.get("colors") or (255, 255, 255)
    duration = float(params.get("duration", 0.35))
    normalized_color = _normalize_color(tuple(color))
    return FlashPattern(color=normalized_color, duration=duration)


def _build_group_cycle(params: Dict[str, Any]) -> LedPattern:
    group_lengths = params.get("group_lengths") or [6, 8, 8, 8]
    background_palette = _normalize_palette(params.get("background_palette") or params.get("palette"))
    background_color_duration = float(params.get("background_color_duration", params.get("color_duration", 2.5)))
    background_pulse_frequency = float(params.get("background_pulse_frequency", params.get("frequency", 0.6)))
    try:
        lengths = [int(length) for length in group_lengths]
    except (TypeError, ValueError):
        lengths = [6, 8, 8, 8]
    return GroupCyclePattern(
        group_lengths=lengths,
        background_palette=background_palette,
        background_color_duration=background_color_duration,
        background_pulse_frequency=background_pulse_frequency,
    )


_PATTERN_BUILDERS: Dict[str, Callable[[Dict[str, Any]], LedPattern]] = {
    "loading_blue_cycle": _build_blue_cycle,
    "story_pulse": _build_story_pulse,
    "flash": _build_flash,
    "flash_play_button": lambda params: _build_flash({"color": (80, 160, 255), "duration": 1.0, **params}),
    "flash_stop_button": lambda params: _build_flash({"color": (255, 0, 0), "duration": 1.0, **params}),
    "flash_internet_connected": lambda params: _build_flash({"color": (0, 255, 0), "duration": 4.0, **params}),
    "preparing_group_cycle": _build_group_cycle,
}


def create_pattern(pattern_id: str, params: Optional[Dict[str, Any]] = None) -> LedPattern:
    builder = _PATTERN_BUILDERS.get(pattern_id)
    if builder is None:
        raise ValueError(f"Unknown LED pattern '{pattern_id}'")
    data = dict(params or {})
    pattern = builder(data)
    if not isinstance(pattern, LedPattern):
        raise TypeError(f"Builder for pattern '{pattern_id}' did not return LedPattern instance")
    return pattern


PATTERN_FACTORIES: Dict[str, PatternFactory] = {
    "loading_blue_cycle": lambda: create_pattern("loading_blue_cycle"),
    "story_pulse": lambda: create_pattern("story_pulse"),
    "flash_play_button": lambda: create_pattern("flash_play_button"),
    "flash_stop_button": lambda: create_pattern("flash_stop_button"),
    "flash_internet_connected": lambda: create_pattern("flash_internet_connected"),
    "preparing_group_cycle": lambda: create_pattern("preparing_group_cycle"),
}


class ScriptedTimelinePattern(LedPattern):
    """Pattern that switches sub-patterns based on a scripted timeline."""

    def __init__(
        self,
        timeline: StoryLedTimeline,
        time_supplier: Callable[[], Optional[float]],
    ) -> None:
        super().__init__(duration=None)
        self._timeline = timeline
        self._time_supplier = time_supplier
        self._segments: List[StoryLedSegment] = list(timeline.segments)
        self._active_segment_index: Optional[int] = None
        self._active_pattern: Optional[LedPattern] = None
        self._fallback_pattern: Optional[LedPattern] = None

    def reset(self, pixel_count: int) -> None:
        super().reset(pixel_count)
        self._active_segment_index = None
        self._active_pattern = None
        self._fallback_pattern = None
        if self._timeline.fallback_pattern_id:
            try:
                fallback = create_pattern(
                    self._timeline.fallback_pattern_id,
                    self._timeline.fallback_params,
                )
                fallback.reset(pixel_count)
                self._fallback_pattern = fallback
            except Exception as exc:
                print(f"[ScriptedTimelinePattern] Failed to build fallback: {exc}")

    def _current_time(self) -> float:
        try:
            value = self._time_supplier()
        except Exception as exc:
            print(f"[ScriptedTimelinePattern] Time supplier error: {exc}")
            return 0.0
        if value is None:
            return 0.0
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return 0.0

    def _segment_end(self, idx: int) -> Optional[float]:
        segment = self._segments[idx]
        if segment.duration is not None:
            return segment.start + segment.duration
        if idx + 1 < len(self._segments):
            return self._segments[idx + 1].start
        return None

    def _select_segment_index(self, current_time: float) -> Optional[int]:
        if not self._segments:
            return None

        for idx, segment in enumerate(self._segments):
            if current_time < segment.start:
                if idx == 0:
                    return 0
                continue

            end_time = self._segment_end(idx)
            if end_time is None or current_time < end_time:
                return idx

        return len(self._segments) - 1

    def render(self) -> List[Color]:
        if self._pixel_count <= 0:
            return []

        current_time = self._current_time()
        segment_index = self._select_segment_index(current_time)

        if segment_index is None:
            if self._fallback_pattern:
                return self._fallback_pattern.render()
            return [(0, 0, 0)] * self._pixel_count

        if segment_index != self._active_segment_index or self._active_pattern is None:
            segment = self._segments[segment_index]
            try:
                pattern = create_pattern(segment.pattern_id, segment.params)
                pattern.reset(self._pixel_count)
                self._active_pattern = pattern
                self._active_segment_index = segment_index
            except Exception as exc:
                print(f"[ScriptedTimelinePattern] Failed to build pattern '{segment.pattern_id}': {exc}")
                self._active_pattern = None
                self._active_segment_index = None

        if not self._active_pattern:
            if self._fallback_pattern:
                return self._fallback_pattern.render()
            return [(0, 0, 0)] * self._pixel_count

        segment = self._segments[self._active_segment_index]
        elapsed = max(0.0, current_time - segment.start)
        if segment.duration is not None:
            elapsed = min(elapsed, segment.duration)
        return self._active_pattern.render_for_elapsed(elapsed)

__all__ = [
    "Color",
    "LedPattern",
    "BlueCyclePattern",
    "StoryPulsePattern",
    "FlashPattern",
    "GroupCyclePattern",
    "create_pattern",
    "ScriptedTimelinePattern",
    "PATTERN_FACTORIES",
]
