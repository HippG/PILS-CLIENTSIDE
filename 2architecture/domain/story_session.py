from dataclasses import dataclass, field
from typing import List, Optional, Dict


@dataclass
class StorySession:
    characters: List[str] = field(default_factory=list)
    duration_mode: str = "medium"  # "short" / "medium" / "long"
    story_audio_path: Optional[str] = None
    led_pattern: Optional[Dict] = None  # pour plus tard (API)
