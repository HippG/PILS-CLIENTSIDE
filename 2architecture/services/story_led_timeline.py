from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class StoryLedSegment:
    start: float
    pattern_id: str
    duration: Optional[float] = None
    params: Dict[str, Any] = field(default_factory=dict)
    end: Optional[float] = None


@dataclass
class StoryLedTimeline:
    segments: List[StoryLedSegment]
    fallback_pattern_id: Optional[str] = None
    fallback_params: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.segments.sort(key=lambda segment: segment.start)


def load_story_led_timeline(path: Path) -> Optional[StoryLedTimeline]:
    if not path or not path.is_file():
        return None

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[StoryLedTimeline] Failed to decode JSON from {path}: {exc}")
        return None
    except OSError as exc:
        print(f"[StoryLedTimeline] Failed to read {path}: {exc}")
        return None

    timeline_entries = raw.get("audio_led_sync")
    if not isinstance(timeline_entries, list):
        print(f"[StoryLedTimeline] Missing 'audio_led_sync' array in {path}")
        return None

    segments: List[StoryLedSegment] = []
    for entry in timeline_entries:
        if not isinstance(entry, dict):
            continue

        pattern_name = entry.get("pattern")
        start = entry.get("start_time")
        if pattern_name is None or start is None:
            continue

        try:
            start_value = max(0.0, float(start))
        except (TypeError, ValueError):
            continue

        end = entry.get("end_time")
        end_value: Optional[float]
        if end is None:
            end_value = None
        else:
            try:
                end_value = max(0.0, float(end))
            except (TypeError, ValueError):
                end_value = None

        duration_value: Optional[float] = None
        if end_value is not None:
            duration_value = max(0.0, end_value - start_value)

        color = _parse_color(entry.get("color"))
        extra_params = {
            k: v
            for k, v in entry.items()
            if k not in {"pattern", "start_time", "end_time", "color"}
        }

        pattern_id, params = _translate_pattern(str(pattern_name), color, duration_value, extra_params)

        segments.append(
            StoryLedSegment(
                start=start_value,
                pattern_id=pattern_id,
                duration=duration_value,
                params=params,
                end=end_value,
            )
        )

    if not segments:
        print(f"[StoryLedTimeline] No valid segments found in {path}")
        return None

    return StoryLedTimeline(
        segments=segments,
        fallback_pattern_id=None,
        fallback_params={},
    )


def _parse_color(data: Any) -> Optional[Tuple[int, int, int]]:
    if isinstance(data, dict):
        r = data.get("r")
        g = data.get("g")
        b = data.get("b")
        components = (r, g, b)
    elif isinstance(data, (list, tuple)):
        components = tuple(data[:3])
    else:
        return None

    normalized: List[int] = []
    for component in components:
        try:
            value = int(round(float(component)))
        except (TypeError, ValueError):
            value = 0
        normalized.append(max(0, min(255, value)))
    while len(normalized) < 3:
        normalized.append(0)
    return tuple(normalized[:3])


def _translate_pattern(
    pattern_name: str,
    color: Optional[Tuple[int, int, int]],
    duration: Optional[float],
    extra: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    translator = _PATTERN_TRANSLATORS.get(pattern_name.lower())
    if translator:
        try:
            return translator(color, duration, extra)
        except Exception as exc:
            print(f"[StoryLedTimeline] Error translating pattern '{pattern_name}': {exc}")

    print(
        f"[StoryLedTimeline] Unknown pattern '{pattern_name}', using default story pulse.")
    return _default_translation(color, duration, extra)


def _default_translation(
    color: Optional[Tuple[int, int, int]],
    duration: Optional[float],
    extra: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    base_color = color or (80, 160, 255)
    palette = [
        list(base_color),
        list(_lighten_color(base_color, 0.35)),
    ]
    params: Dict[str, Any] = {
        "palette": palette,
        "color_duration": _safe_float(extra.get("color_duration"), default=2.8),
        "pulse_frequency": _safe_float(extra.get("pulse_frequency"), default=0.55),
    }
    return "story_pulse", params


def _translate_vent(
    color: Optional[Tuple[int, int, int]],
    duration: Optional[float],
    extra: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    highlight = color or (60, 140, 255)
    background = extra.get("background")
    if isinstance(background, dict):
        background_color = _parse_color(background)
    elif isinstance(background, (list, tuple)):
        background_color = _parse_color(tuple(background))
    else:
        background_color = None
    if background_color is None:
        background_color = tuple(max(0, min(255, int(component * 0.15))) for component in highlight)
    params = {
        "highlight": list(highlight),
        "background": list(background_color),
        "tail_length": _safe_int(extra.get("tail_length"), default=6),
        "speed_leds_per_sec": _safe_float(extra.get("speed_leds_per_sec"), default=9.0),
    }
    return "loading_blue_cycle", params


def _translate_flashing(
    color: Optional[Tuple[int, int, int]],
    duration: Optional[float],
    extra: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    base_duration = duration if duration and duration > 0 else _safe_float(extra.get("duration"), default=0.5)
    params = {
        "color": list(color or (255, 255, 255)),
        "duration": _safe_float(base_duration, default=0.5),
    }
    return "flash", params


def _translate_pulse_doux(
    color: Optional[Tuple[int, int, int]],
    duration: Optional[float],
    extra: Dict[str, Any],
) -> Tuple[str, Dict[str, Any]]:
    base_color = color or (255, 120, 30)
    palette = [
        list(base_color),
        list(_lighten_color(base_color, 0.25)),
        list(_lighten_color(base_color, 0.5)),
    ]
    params = {
        "palette": palette,
        "pulse_frequency": _safe_float(extra.get("pulse_frequency"), default=0.45),
        "color_duration": _safe_float(
            extra.get("color_duration"),
            default=max(duration or 2.5, 1.5),
        ),
    }
    return "story_pulse", params


def _lighten_color(color: Tuple[int, int, int], factor: float) -> Tuple[int, int, int]:
    clamped = max(0.0, min(1.0, factor))
    return tuple(
        max(0, min(255, int(round(component + (255 - component) * clamped))))
        for component in color
    )


_PATTERN_TRANSLATORS: Dict[
    str,
    Callable[[Optional[Tuple[int, int, int]], Optional[float], Dict[str, Any]], Tuple[str, Dict[str, Any]]],
] = {
    # Legacy pattern names: map to existing implementations
    "bluecycle": _translate_vent,
    "blue_cycle": _translate_vent,
    "story_pulse": _default_translation,
    "flash": _translate_flashing,
    # New names supplied by story scripts, reuse existing implementations
    "vent": _translate_vent,
    "flashing": _translate_flashing,
    "pulse_doux": _translate_pulse_doux,
}


def _safe_float(value: Any, default: float) -> float:
    try:
        if value is None:
            raise ValueError
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: Any, default: int) -> int:
    try:
        if value is None:
            raise ValueError
        return int(value)
    except (TypeError, ValueError):
        return int(default)
