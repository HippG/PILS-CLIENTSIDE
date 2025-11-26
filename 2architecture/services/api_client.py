import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import requests


@dataclass
class CharacterInfo:
    name: str
    group_color: Optional[Tuple[int, int, int]] = None


class StoryApiClient:
    """Simple wrapper around the local story API."""

    def __init__(self, base_url: str = "http://127.0.0.1:8000", timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_character(self, tag_id: int) -> Optional[CharacterInfo]:
        url = f"{self.base_url}/get-character"
        try:
            response = requests.get(url, params={"tag_id": tag_id}, timeout=self.timeout)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"[StoryApiClient] Character lookup failed for tag {tag_id}: {exc}")
            return None

        try:
            data = response.json()
        except ValueError:
            print(f"[StoryApiClient] Invalid JSON when decoding character for tag {tag_id}.")
            return None

        if not isinstance(data, dict):
            print(f"[StoryApiClient] Unexpected payload for tag {tag_id}: {data}")
            return None

        name = data.get("name")
        if not name:
            print(f"[StoryApiClient] Response missing 'name' for tag {tag_id}: {data}")
            return None

        group_color = self._parse_color_payload(data.get("group_color"), tag_id)
        return CharacterInfo(name=name, group_color=group_color)

    def get_character_name(self, tag_id: int) -> Optional[str]:
        info = self.get_character(tag_id)
        return info.name if info else None

    def generate_story(self, duration: str, characters: List[str], output_dir: Path) -> Optional[Path]:
        url = f"{self.base_url}/generate-story"
        payload = {
            "duration": duration,
            "characters": characters,
        }

        try:
            response = requests.post(url, json=payload, timeout=self.timeout, stream=True)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"[StoryApiClient] Story generation request failed: {exc}")
            return None

        output_dir.mkdir(parents=True, exist_ok=True)

        filename = None
        content_disposition = response.headers.get("Content-Disposition", "")
        if "filename=" in content_disposition:
            filename = content_disposition.split("filename=")[-1].strip("\"' ")

        if not filename:
            timestamp = int(time.time())
            filename = f"story_{timestamp}.mp3"

        target_path = output_dir / filename

        try:
            with target_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        handle.write(chunk)
        except OSError as exc:
            print(f"[StoryApiClient] Failed to write story file {target_path}: {exc}")
            return None

        print(f"[StoryApiClient] Story saved to {target_path}")
        return target_path

    def _parse_color_payload(self, payload, tag_id: int) -> Optional[Tuple[int, int, int]]:
        if payload is None:
            return None

        if isinstance(payload, dict):
            try:
                r = int(payload["r"])
                g = int(payload["g"])
                b = int(payload["b"])
                rgb = (r, g, b)
            except (KeyError, TypeError, ValueError):
                print(f"[StoryApiClient] Invalid color payload for tag {tag_id}: {payload}")
                return None
            if all(0 <= channel <= 255 for channel in rgb):
                return rgb
            print(f"[StoryApiClient] Ignoring out-of-range color for tag {tag_id}: {payload}")
            return None

        if isinstance(payload, str):
            hex_value = payload.lstrip("#")
            if len(hex_value) == 6:
                try:
                    return tuple(int(hex_value[i:i+2], 16) for i in (0, 2, 4))
                except ValueError:
                    print(f"[StoryApiClient] Invalid hex color for tag {tag_id}: {payload}")
                    return None
            print(f"[StoryApiClient] Unsupported color string for tag {tag_id}: {payload}")
            return None

        print(f"[StoryApiClient] Unsupported color type for tag {tag_id}: {payload}")
        return None
