#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time
import threading


class StopButton:
    """
    Gère un bouton simple (pull-up) avec callback sur pression.
    """

    def __init__(self, pin: int, on_press):
        self.pin = pin
        self.on_press = on_press

        GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        self._thread = None
        self._stop_flag = False

    def start(self):
        print(f"[StopButton] Starting thread on GPIO {self.pin}")
        self._stop_flag = False

        def run():
            last_state = GPIO.input(self.pin)
            while not self._stop_flag:
                current = GPIO.input(self.pin)
                if current != last_state:
                    # front descendant => bouton pressé
                    if current == GPIO.LOW:
                        print("[StopButton] Button pressed.")
                        try:
                            self.on_press()
                        except Exception as e:
                            print("[StopButton] Error in on_press callback:", e)
                        time.sleep(0.2)  # anti-rebond simple
                    last_state = current
                time.sleep(0.01)
            print("[StopButton] Thread stopped.")

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_flag = True
