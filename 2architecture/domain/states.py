from enum import Enum, auto


class StoryBoxState(Enum):
    BOOTING = auto()
    WAITING_NETWORK = auto()
    IDLE_READY = auto()
    PREPARING_STORY = auto()
    REQUESTING_STORY = auto()
    PLAYING_STORY = auto()
    PAUSED = auto()
    CONFIRM_STOP = auto()
