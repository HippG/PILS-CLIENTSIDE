from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class StorySession:
    figure_rfid_uids: List[int] = field(default_factory=list)
    duration_mode: str = "medium"
    story_audio_path: Optional[str] = None
    led_pattern_path: Optional[str] = None
