import threading
import board
import neopixel


class LedDriver:
    """
    Driver de base pour ruban NeoPixel.
    Ici on se contente de pouvoir fixer une couleur globale ou tout éteindre.
    """

    def __init__(self, led_pin=board.D13, led_count=30, brightness=1.0):
        self.led_count = led_count
        self._lock = threading.Lock()
        self.pixels = neopixel.NeoPixel(
            led_pin,
            led_count,
            brightness=brightness,
            auto_write=False,
            pixel_order=neopixel.GRB
        )
        print(f"[LedDriver] Initialized with {led_count} LEDs on {led_pin}.")

    def set_color(self, r: int, g: int, b: int):
        self.set_pixels([(r, g, b)] * self.led_count)

    def set_pixels(self, colors):
        if len(colors) != self.led_count:
            raise ValueError(f"Expected {self.led_count} colors, received {len(colors)}")

        # Ensure tuple of ints to avoid neopixel surprises.
        safe_colors = [tuple(max(0, min(255, int(c))) for c in color) for color in colors]

        with self._lock:
            for idx, color in enumerate(safe_colors):
                self.pixels[idx] = color
            self.pixels.show()

    def off(self):
        self.set_color(0, 0, 0)
