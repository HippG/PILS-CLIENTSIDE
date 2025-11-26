#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time
import threading


class RotaryEncoder:
    """
    Wrap du KY-040.
    - rotation → on_rotate(delta: +1/-1)
    - clic SW   → on_click()
    """

    def __init__(self, clk_pin: int, dt_pin: int, sw_pin: int, on_click, on_rotate):
        self.clk_pin = clk_pin
        self.dt_pin = dt_pin
        self.sw_pin = sw_pin

        self.on_click = on_click
        self.on_rotate = on_rotate

        GPIO.setup(self.clk_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.dt_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.sw_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        self._thread = None
        self._stop_flag = False

    def start(self):
        print(f"[RotaryEncoder] Starting thread (CLK={self.clk_pin}, DT={self.dt_pin}, SW={self.sw_pin})")
        self._stop_flag = False

        def run():
            last_clk_state = GPIO.input(self.clk_pin)
            last_sw_state = GPIO.input(self.sw_pin)

            while not self._stop_flag:
                clk_state = GPIO.input(self.clk_pin)
                dt_state = GPIO.input(self.dt_pin)
                sw_state = GPIO.input(self.sw_pin)

                # Rotation
                if clk_state != last_clk_state:
                    if dt_state != clk_state:
                        delta = +1
                        direction = "clockwise"
                    else:
                        delta = -1
                        direction = "counter-clockwise"

                    print(f"[RotaryEncoder] Rotated {direction} (delta={delta})")
                    try:
                        self.on_rotate(delta)
                    except Exception as e:
                        print("[RotaryEncoder] Error in on_rotate callback:", e)

                last_clk_state = clk_state

                # Clic sur SW (front descendant)
                if sw_state != last_sw_state and sw_state == GPIO.LOW:
                    print("[RotaryEncoder] Button clicked.")
                    try:
                        self.on_click()
                    except Exception as e:
                        print("[RotaryEncoder] Error in on_click callback:", e)
                    time.sleep(0.2)  # anti-rebond

                last_sw_state = sw_state

                time.sleep(0.001)

            print("[RotaryEncoder] Thread stopped.")

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_flag = True
