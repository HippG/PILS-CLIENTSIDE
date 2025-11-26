import neopixel
import board
import time


class LedDriver:
    """
    Driver de base pour ruban NeoPixel.
    Ici on se contente de pouvoir fixer une couleur globale ou tout éteindre.
    """

    def __init__(self, led_pin=board.D12, led_count=30, brightness=0.5):
        self.led_count = led_count
        self.pixels = neopixel.NeoPixel(
            led_pin,
            led_count,
            brightness=brightness,
            auto_write=False,
            pixel_order=neopixel.GRB
        )
        print(f"[LedDriver] Initialized with {led_count} LEDs on {led_pin}.")

    def set_color(self, r: int, g: int, b: int):
        for i in range(self.led_count):
            self.pixels[i] = (r, g, b)
        self.pixels.show()
        # debug léger
        # print(f"[LedDriver] Color set to ({r},{g},{b}).")

    def off(self):
        self.set_color(0, 0, 0)
        # print("[LedDriver] LEDs off.")
