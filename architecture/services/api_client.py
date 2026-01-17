import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import requests


@dataclass
class CharacterInfo:
    name: str
    group_color: Optional[Tuple[int, int, int]] = None


@dataclass
class GeneratedStoryAssets:
    audio_path: Path
    led_pattern_path: Path


class StoryApiClient:
    """Simple wrapper around the local story API."""

    def __init__(self, base_url: str = "http://13.38.48.162:8000", timeout: float = 300.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def get_character(self, tag_id: int) -> Optional[CharacterInfo]:
        url = f"{self.base_url}/characters/character_id/{tag_id}"
        try:
            response = requests.get(url, timeout=self.timeout)
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

        name = str(data.get("character_id"))
        if not name:
            print(f"[StoryApiClient] Response missing 'name' for tag {tag_id}: {data}")
            return None

        group_color = self._parse_color_payload(data.get("color"), tag_id)
        return CharacterInfo(name=name, group_color=group_color)

    def get_character_name(self, tag_id: int) -> Optional[str]:
        info = self.get_character(tag_id)
        return info.name if info else None

    def generate_story(self, duration: str, figure_rfid_uids: List[int], output_dir: Path) -> Optional[GeneratedStoryAssets]:
        url = f"{self.base_url}/stories/generate"

        if duration == "short":
            duration = 1
        elif duration == "medium":
            duration = 5
        elif duration == "long":
            duration = 10

        payload = {
            "duration": duration,
            "figure_rfid_uids": figure_rfid_uids,
            "milo_id":1,
        }

        print("[API] POST", url)
        print("[API] Payload:", payload)

        try:

            response = requests.post(url, json=payload, timeout=self.timeout, stream=True)
            response.raise_for_status()
        except requests.RequestException as exc:
            print(f"[StoryApiClient] Story generation request failed: {exc}")
            return None

        output_dir.mkdir(parents=True, exist_ok=True)

        filename = None
        story_id = int(time.time())
        content_disposition = response.headers.get("Content-Disposition", "")
        if "filename=" in content_disposition:
            filename = content_disposition.split("filename=")[-1].strip("\"' ")

        if not filename:
            filename = f"story_{story_id}.zip"

        archive_path = output_dir / filename

        try:
            with archive_path.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        handle.write(chunk)
        except OSError as exc:
            print(f"[StoryApiClient] Failed to write archive {archive_path}: {exc}")
            return None

        story_target = output_dir / f"story_{story_id}.mp3"
        leds_target = output_dir / f"leds_timing_{story_id}.json"

        while story_target.exists() or leds_target.exists():
            story_id += 1
            story_target = output_dir / f"story_{story_id}.mp3"
            leds_target = output_dir / f"leds_timing_{story_id}.json"

        try:
            with zipfile.ZipFile(archive_path, "r") as archive:
                story_member = None
                leds_member = None

                for member in archive.namelist():
                    if member.endswith("/"):
                        continue
                    name_lower = Path(member).name.lower()
                    if name_lower.endswith(".mp3") and story_member is None:
                        story_member = member
                    elif name_lower.endswith(".json") and leds_member is None:
                        leds_member = member

                if story_member is None:
                    print("[StoryApiClient] Archive missing story audio file.")
                    return None
                if leds_member is None:
                    print("[StoryApiClient] Archive missing LED timeline file.")
                    return None

                with archive.open(story_member) as src, story_target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

                with archive.open(leds_member) as src, leds_target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

        except (zipfile.BadZipFile, OSError) as exc:
            print(f"[StoryApiClient] Failed to extract story archive: {exc}")
            for leftover in (story_target, leds_target):
                try:
                    if leftover.exists():
                        leftover.unlink()
                except OSError:
                    pass
            return None
        finally:
            try:
                archive_path.unlink()
            except OSError:
                pass

        print(f"[StoryApiClient] Story saved to {story_target} with LEDs {leds_target}")
        return GeneratedStoryAssets(audio_path=story_target, led_pattern_path=leds_target)

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
