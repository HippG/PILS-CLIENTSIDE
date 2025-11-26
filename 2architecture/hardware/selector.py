#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time
import threading


class DurationSelector:
    """
    Sélecteur 3 positions sur 2 entrées:
    - SW1 LOW, SW2 HIGH  → "short"
    - SW1 HIGH, SW2 HIGH → "medium"
    - SW1 HIGH, SW2 LOW  → "long"
    """

    def __init__(self, sw1_pin: int, sw2_pin: int, on_duration_change):
        self.sw1_pin = sw1_pin
        self.sw2_pin = sw2_pin
        self.on_duration_change = on_duration_change

        GPIO.setup(self.sw1_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.setup(self.sw2_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        self._thread = None
        self._stop_flag = False
        self._current_mode = None

    def read_mode(self) -> str:
        s1 = GPIO.input(self.sw1_pin)
        s2 = GPIO.input(self.sw2_pin)

        if s1 == GPIO.LOW and s2 == GPIO.HIGH:
            return "short"
        elif s1 == GPIO.HIGH and s2 == GPIO.HIGH:
            return "medium"
        elif s1 == GPIO.HIGH and s2 == GPIO.LOW:
            return "long"
        else:
            return "unknown"

    def start(self):
        print(f"[DurationSelector] Starting thread (SW1={self.sw1_pin}, SW2={self.sw2_pin})")
        self._stop_flag = False

        def run():
            last_mode = self.read_mode()
            self._current_mode = last_mode
            print(f"[DurationSelector] Initial mode: {last_mode}")

            # notifier une première fois si le mode est valide
            if last_mode != "unknown":
                try:
                    self.on_duration_change(last_mode)
                except Exception as e:
                    print("[DurationSelector] Error in on_duration_change callback:", e)

            while not self._stop_flag:
                mode = self.read_mode()
                if mode != last_mode and mode != "unknown":
                    print(f"[DurationSelector] Mode changed: {last_mode} → {mode}")
                    self._current_mode = mode
                    last_mode = mode
                    try:
                        self.on_duration_change(mode)
                    except Exception as e:
                        print("[DurationSelector] Error in on_duration_change callback:", e)
                time.sleep(0.1)

            print("[DurationSelector] Thread stopped.")

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_flag = True

