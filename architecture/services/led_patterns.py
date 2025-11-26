# led_patterns.py
from typing import List, Tuple
import math, time
import random
from typing import List, Optional, Tuple

Color = Tuple[int, int, int]

def _clamp(x: float) -> int:
    return max(0, min(255, int(x)))

def _scale(color: Color, f: float) -> Color:
    return (_clamp(color[0]*f), _clamp(color[1]*f), _clamp(color[2]*f))

def _lerp(a: Color, b: Color, t: float) -> Color:
    t = max(0.0, min(1.0, t))
    return (_clamp(a[0]+(b[0]-a[0])*t),
            _clamp(a[1]+(b[1]-a[1])*t),
            _clamp(a[2]+(b[2]-a[2])*t))

class LedPattern:
    def __init__(self, duration: float | None = None):
        self._duration = duration
        self._start = None
        self._pixel_count = 0

    def reset(self, count: int):
        self._pixel_count = count
        self._start = time.monotonic()
        self.on_reset()

    def on_reset(self): pass

    def elapsed(self):
        return 0 if not self._start else time.monotonic() - self._start

    def is_finished(self):
        return self._duration and self.elapsed() >= self._duration

    def render(self):
        raise NotImplementedError


class CyclePattern(LedPattern):
    def __init__(self, color=(255,255,255), background=(0,0,0), speed=10.0, tail=6):
        super().__init__()
        self.color, self.bg, self.speed, self.tail = color, background, speed, tail

    def render(self):
        if self._pixel_count <= 0: return []
        t = self.elapsed()
        head = (t*self.speed) % self._pixel_count
        out = []
        for i in range(self._pixel_count):
            d = min(abs(i - head), self._pixel_count - abs(i - head))
            intensity = max(0.0, 1.0 - d/self.tail)
            out.append(_lerp(self.bg, self.color, intensity))
        return out


class InstantFlashPattern(LedPattern):
    def __init__(self, color=(255,255,255), duration=0.5):
        super().__init__(duration)
        self.color = color

    def render(self):
        progress = min(1.0, self.elapsed()/self._duration)
        intensity = 1.0 - progress
        return [_scale(self.color, intensity)] * self._pixel_count


class FillPattern(LedPattern):
    """Simple remplissage uniforme"""
    def __init__(self, color=(255,255,255)):
        super().__init__()
        self.color = color

    def render(self):
        return [self.color] * self._pixel_count

class BreatheSlowPattern(LedPattern):
    """
    Smoothly fades from a color to black and back again ("breathing" effect).
    Arguments:
        color: base color (tuple RGB 0–255)
        delay: time (in seconds) for a full breathe cycle (color → black → color)
    """

    def __init__(self, color=(255, 255, 255)):
        super().__init__()
        self.color = color
        self.delay = 2.0

    def render(self):
        n = self._pixel_count
        if n <= 0:
            return []

        t = self.elapsed()
        # Compute phase in [0, 1): color -> black -> color
        phase = (t % self.delay) / self.delay
        # Use cosine for smooth breathing (goes 1→0→1)
        intensity = 0.5 * (1 - math.cos(phase * 2 * math.pi))

        color = _scale(self.color, intensity)
        return [color] * n

class BreatheFastPattern(LedPattern):
    """
    Smoothly fades from a color to black and back again ("breathing" effect).
    Arguments:
        color: base color (tuple RGB 0–255)
        delay: time (in seconds) for a full breathe cycle (color → black → color)
    """

    def __init__(self, color=(255, 255, 255)):
        super().__init__()
        self.color = color
        self.delay = 0.4

    def render(self):
        n = self._pixel_count
        if n <= 0:
            return []

        t = self.elapsed()
        # Compute phase in [0, 1): color -> black -> color
        phase = (t % self.delay) / self.delay
        # Use cosine for smooth breathing (goes 1→0→1)
        intensity = 0.5 * (1 - math.cos(phase * 2 * math.pi))

        color = _scale(self.color, intensity)
        return [color] * n



class GroupCyclePattern(LedPattern):
    """
    Pattern d'arrière-plan avec animation douce et gestion de groupes.
    - Chaque groupe correspond à une portion du ruban.
    - Chaque groupe peut être coloré indépendamment (via set_group_color).
    - Le fond est une pulsation colorée douce, peu lumineuse.
    """

    def __init__(
        self,
        group_lengths: List[int] | None = None,
        background_palette: Optional[List[Color]] = None,
        color_duration: float = 3.0,
        pulse_frequency: float = 0.5,
    ) -> None:
        super().__init__(duration=None)

        # Définition des groupes (longueurs relatives)
        self._base_lengths = group_lengths or [1]
        self._groups: List[Tuple[int, int]] = []
        self._group_overrides: List[Optional[Color]] = []
        self._pixel_group_index: List[int] = []

        # Palette de fond
        self._palette = background_palette or [
            (20, 10, 60),
            (30, 0, 30),
        ]
        self._color_duration = max(0.1, color_duration)
        self._pulse_frequency = pulse_frequency

    # ----------------------------------------------------------------------

    def on_reset(self) -> None:
        """Recalcule la structure des groupes en fonction du nombre de LEDs."""
        total = sum(self._base_lengths)
        n = self._pixel_count

        if total <= 0 or n <= 0:
            self._groups = []
            self._group_overrides = []
            self._pixel_group_index = []
            return

        # Calcul de la répartition des LEDs entre les groupes
        scale = n / total
        indices: List[Tuple[int, int]] = []
        cursor = 0
        remaining_pixels = n
        remaining_groups = len(self._base_lengths)

        for length in self._base_lengths:
            remaining_groups -= 1
            target = max(1, int(round(length * scale)))
            if remaining_groups == 0:
                target = remaining_pixels
            else:
                target = min(target, remaining_pixels - remaining_groups)

            start = cursor
            stop = min(n, start + target)
            indices.append((start, stop))
            cursor = stop
            remaining_pixels = max(0, n - cursor)

        self._groups = [g for g in indices if g[1] > g[0]]
        self._group_overrides = [None] * len(self._groups)

        # Mapping pixel → groupe
        self._pixel_group_index = [-1] * n
        for group_index, (start, stop) in enumerate(self._groups):
            for i in range(start, stop):
                self._pixel_group_index[i] = group_index

    # ----------------------------------------------------------------------

    def set_group_color(self, group_index: int, color: Color) -> None:
        """Force la couleur d’un groupe (par exemple lorsqu’un RFID est détecté)."""
        if 0 <= group_index < len(self._group_overrides):
            self._group_overrides[group_index] = color

    def clear_group_color(self, group_index: int) -> None:
        """Réinitialise la couleur d’un groupe à la couleur de fond."""
        if 0 <= group_index < len(self._group_overrides):
            self._group_overrides[group_index] = None

    def clear_all_group_colors(self) -> None:
        """Réinitialise toutes les couleurs de groupes."""
        for i in range(len(self._group_overrides)):
            self._group_overrides[i] = None

    # ----------------------------------------------------------------------

    def _background_color(self, elapsed: float) -> Color:
        """Calcule la couleur du fond pulsant."""
        if not self._palette:
            return (0, 0, 0)

        cycle_length = self._color_duration * len(self._palette)
        color_position = elapsed % cycle_length
        segment_index = int(color_position / self._color_duration)
        blend_t = (color_position % self._color_duration) / self._color_duration

        base_color = self._palette[segment_index % len(self._palette)]
        next_color = self._palette[(segment_index + 1) % len(self._palette)]
        blended = _lerp(base_color, next_color, blend_t)

        # Effet de pulsation douce
        brightness = 0.25 + 0.75 * (
            0.5 * (1.0 + math.sin(elapsed * self._pulse_frequency * 2 * math.pi))
        )
        return _scale(blended, brightness)

    # ----------------------------------------------------------------------

    def render(self) -> List[Color]:
        """Construit la frame actuelle (fond + groupes colorés)."""
        elapsed = self.elapsed()
        n = self._pixel_count
        if n <= 0:
            return []

        bg_color = self._background_color(elapsed)
        pixels = [bg_color] * n

        # Applique les couleurs des groupes actifs
        for i in range(n):
            group_index = self._pixel_group_index[i] if i < len(self._pixel_group_index) else -1
            if 0 <= group_index < len(self._group_overrides):
                override = self._group_overrides[group_index]
                if override is not None:
                    pixels[i] = override

        return pixels
    

class FirePattern(LedPattern):
    """
    Effet de lave dynamique et organique :
    - Plus rapide et plus contrastée
    - Couleurs rouges/oranges sombres, pas de blancs
    - Chaque LED légèrement différente
    """

    def __init__(self):
        super().__init__()
        self._palette = [
            (40, 0, 0),     # rouge noir
            (100, 10, 0),   # rouge profond
            (160, 30, 0),   # rouge chaud
            (220, 50, 0),   # orange foncé
            (255, 80, 0),   # orange chaud
        ]
        self._speed = 0.6      # vitesse du flux
        self._spatial_scale = 0.35  # influence entre LEDs

    def _blend_palette(self, t: float) -> Color:
        i = int(t * len(self._palette)) % len(self._palette)
        j = (i + 1) % len(self._palette)
        f = t * len(self._palette) - int(t * len(self._palette))
        return _lerp(self._palette[i], self._palette[j], f)

    def render(self):
        n = self._pixel_count
        if n <= 0:
            return []

        t = self.elapsed()
        pixels = []

        # Texture dynamique : variation spatiale et temporelle
        for i in range(n):
            # Bruit organique : mélange sinusoïdal et aléatoire lent
            v = (
                0.6 * math.sin(i * self._spatial_scale + t * self._speed) +
                0.4 * math.sin(i * self._spatial_scale * 1.8 - t * self._speed * 0.9) +
                0.2 * math.sin(i * 0.7 + t * 1.1)
            )
            v += random.uniform(-0.05, 0.05)  # micro-variation

            color_t = (0.5 + 0.5 * v) % 1.0
            color = self._blend_palette(color_t)

            # Variation de luminosité fluide mais perceptible
            brightness = 0.5 + 0.5 * math.sin(t * 1.2 + i * 0.15 + v * 2.0)
            brightness = max(0.2, min(1.0, brightness))

            pixels.append(_scale(color, brightness))

        return pixels

class CornerBlastPattern(LedPattern):
    """
    Effet 'CornerBlast' :
    - Éclaire un groupe de LEDs à la fois (groupes : [6,8,8,8])
    - Chaque groupe reste allumé 0.1s à 0.5s
    - Légère variation de couleur (+/-10%) à chaque éclair
    """

    def __init__(self, color=(255, 80, 0)):
        super().__init__()
        self.color = color
        self._groups = [(0, 6), (6, 14), (14, 22), (22, 30)]
        self._active_group = None
        self._next_switch = 0.0
        self._current_duration = 0.0
        self._current_color = color

    def on_reset(self):
        self._pick_new_group()

    def _vary_color(self, color: Color, variation: float = 0.4) -> Color:
        """Applique une légère variation +/-variation à chaque canal."""
        r, g, b = color
        vr = r * (1 + random.uniform(-variation, variation))
        vg = g * (1 + random.uniform(-variation, variation))
        vb = b * (1 + random.uniform(-variation, variation))
        return (_clamp(vr), _clamp(vg), _clamp(vb))

    def _pick_new_group(self):
        """Choisit un nouveau groupe (différent du précédent) et durée aléatoire."""
        previous = self._active_group

        # Tire un groupe différent du précédent
        possible_groups = [g for g in self._groups if g != previous]
        self._active_group = random.choice(possible_groups)

        # Durée et couleur aléatoires
        self._current_duration = random.uniform(0.1, 0.5)
        self._next_switch = self.elapsed() + self._current_duration
        self._current_color = self._vary_color(self.color)


    def render(self):
        n = self._pixel_count
        if n <= 0:
            return []

        now = self.elapsed()

        # Si le temps est écoulé, on change de groupe
        if now >= self._next_switch:
            self._pick_new_group()

        pixels = [(0, 0, 0)] * n
        if self._active_group:
            start, end = self._active_group
            for i in range(start, min(end, n)):
                pixels[i] = self._current_color

        return pixels


class RainPattern(LedPattern):
    """
    Effet 'RainPattern' :
    - Simule la pluie : quelques gouttes tombent de façon aléatoire.
    - Couleurs bleues froides et profondes.
    - Chaque goutte s’étend légèrement aux LEDs adjacentes en s’éteignant.
    """

    def __init__(self):
        super().__init__()
        self._drops = []  # [(index, start_time, duration, color), ...]
        self._palette = [
            (40, 80, 255),   # bleu vif
            (20, 40, 180),   # bleu foncé
            (60, 100, 220),  # bleu moyen
            (10, 20, 120),   # bleu profond
        ]

    def _random_color(self) -> Color:
        """Choisit une couleur de pluie aléatoire dans des tons bleus."""
        base = random.choice(self._palette)
        return (
            _clamp(base[0] * random.uniform(0.9, 1.1)),
            _clamp(base[1] * random.uniform(0.9, 1.1)),
            _clamp(base[2] * random.uniform(0.9, 1.1)),
        )

    def _spawn_drop(self):
        """Crée une nouvelle goutte bleue."""
        if self._pixel_count <= 0:
            return
        index = random.randint(0, self._pixel_count - 1)
        duration = random.uniform(0.5, 1.5)
        color = self._random_color()
        self._drops.append((index, self.elapsed(), duration, color))

    def render(self):
        n = self._pixel_count
        if n <= 0:
            return []

        now = self.elapsed()
        pixels = [(0, 0, 0)] * n

        # ↓ Densité fortement réduite
        if random.random() < 0.08:
            self._spawn_drop()

        new_drops = []
        for index, start, duration, color in self._drops:
            age = now - start
            if age < duration:
                fade = 1.0 - (age / duration)

                # Expansion douce
                radius = int(1 + 1.5 * (age / duration))  # 1 à 2 pixels

                for offset in range(-radius, radius + 1):
                    pos = index + offset
                    if 0 <= pos < n:
                        dist = abs(offset) / (radius + 0.001)
                        intensity = fade * (1.0 - dist)
                        if intensity > 0:
                            c_scaled = _scale(color, intensity)
                            pr, pg, pb = pixels[pos]
                            nr, ng, nb = c_scaled
                            pixels[pos] = (
                                min(255, pr + nr),
                                min(255, pg + ng),
                                min(255, pb + nb),
                            )

                new_drops.append((index, start, duration, color))

        self._drops = new_drops
        return pixels


class FlashPattern(LedPattern):
    """
    Effet 'FlashingPattern' :
    - Simule un éclair : s'allume brutalement, puis s'éteint lentement.
    - Les éclairs apparaissent à intervalles aléatoires.
    - Couleur configurable.
    """

    def __init__(self, color=(255, 255, 255)):
        super().__init__()
        self.color = color
        self._next_flash = 0.0
        self._flash_start = None
        self._flash_duration = 0.0
        self._active = False

    def _schedule_next_flash(self):
        """Définit quand aura lieu le prochain éclair."""
        # Délai aléatoire entre 1.5 et 5 secondes
        self._next_flash = self.elapsed() + random.uniform(0.3, 1.5)

    def on_reset(self):
        self._schedule_next_flash()

    def render(self):
        now = self.elapsed()
        n = self._pixel_count
        if n <= 0:
            return []

        # Démarre un nouvel éclair
        if not self._active and now >= self._next_flash:
            self._active = True
            self._flash_start = now
            self._flash_duration = random.uniform(0.2, 1.0)
            # Prochaine planification
            self._schedule_next_flash()

        pixels = [(0, 0, 0)] * n

        if self._active:
            age = now - self._flash_start
            if age <= self._flash_duration:
                # Intensité : montée brutale (0→0.05s), décroissance douce ensuite
                if age < 0.05:
                    intensity = 1.0  # flash instantané
                else:
                    fade = (age - 0.05) / (self._flash_duration - 0.05)
                    intensity = max(0.0, 1.0 - fade)

                c = _scale(self.color, intensity)
                pixels = [c] * n
            else:
                # Fin de l’éclair
                self._active = False

        return pixels

class SparklePattern(LedPattern):
    """
    Effet scintillant ('sparkle') :
    - Des étincelles apparaissent aléatoirement dans le ruban
    - Chaque étincelle démarre avec une couleur proche de la couleur d'origine (+/-30%)
    - Elle s'éteint ensuite lentement jusqu'au noir
    """

    def __init__(self, color=(255, 255, 255)):
        super().__init__()
        self.color = color
        # Liste des étincelles actives : [(index, start_time, duration, color), ...]
        self._sparkles = []

    def _vary_color(self, color: Color, variation: float = 0.3) -> Color:
        """Retourne une couleur légèrement altérée (+/-variation)."""
        r, g, b = color
        vr = r * (1 + random.uniform(-variation, variation))
        vg = g * (1 + random.uniform(-variation, variation))
        vb = b * (1 + random.uniform(-variation, variation))
        return (_clamp(vr), _clamp(vg), _clamp(vb))

    def _spawn_sparkle(self):
        """Crée une nouvelle étincelle avec couleur et durée aléatoires."""
        if self._pixel_count <= 0:
            return
        index = random.randint(0, self._pixel_count - 1)
        duration = random.uniform(0.3, 1.2)
        sparkle_color = self._vary_color(self.color, 0.3)
        self._sparkles.append((index, self.elapsed(), duration, sparkle_color))

    def render(self):
        n = self._pixel_count
        if n <= 0:
            return []

        now = self.elapsed()
        pixels = [(0, 0, 0)] * n

        # Probabilité d'apparition d'une nouvelle étincelle
        if random.random() < 0.15:
            self._spawn_sparkle()

        new_sparkles = []
        for index, start, duration, sparkle_color in self._sparkles:
            age = now - start
            if age < duration:
                # Décroissance progressive de l’intensité
                fade = 1.0 - (age / duration)
                color = _scale(sparkle_color, fade)
                pixels[index] = color
                new_sparkles.append((index, start, duration, sparkle_color))

        self._sparkles = new_sparkles
        return pixels
