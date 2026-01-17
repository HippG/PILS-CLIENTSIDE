#!/usr/bin/env python3
import RPi.GPIO as GPIO
import time
import threading


class PlayPauseButton:
    """
    Manages a button (pull-up) with short and long press detection.
    """

    def __init__(self, pin: int, on_short_press, on_long_press=None, long_press_duration=5.0):
        self.pin = pin
        self.on_short_press = on_short_press
        self.on_long_press = on_long_press
        self.long_press_duration = long_press_duration

        GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        self._thread = None
        self._stop_flag = False
        self._long_press_timer = None
        self._long_press_triggered = False

    def start(self):
        print(f"[PlayPauseButton] Starting thread on GPIO {self.pin}")
        self._stop_flag = False

        def run():
            last_state = GPIO.input(self.pin)
            while not self._stop_flag:
                current = GPIO.input(self.pin)
                if current != last_state:
                    # Falling edge => Button pressed
                    if current == GPIO.LOW:
                        print("[PlayPauseButton] Button pressed.")
                        self._long_press_triggered = False
                        # Start timer for long press
                        if self.on_long_press:
                            self._long_press_timer = threading.Timer(self.long_press_duration, self._on_long_press_callback)
                            self._long_press_timer.start()
                    
                    # Rising edge => Button released
                    else:
                        print("[PlayPauseButton] Button released.")
                        # Cancel timer if it's running
                        if self._long_press_timer:
                            self._long_press_timer.cancel()
                            self._long_press_timer = None
                        
                        # Trigger short press ONLY if long press hasn't triggered
                        if not self._long_press_triggered:
                            try:
                                self.on_short_press()
                            except Exception as e:
                                print("[PlayPauseButton] Error in on_short_press callback:", e)
                        
                        self._long_press_triggered = False

                    time.sleep(0.05) # Debounce
                    last_state = current
                time.sleep(0.01)
            
            # Cleanup on stop
            if self._long_press_timer:
                self._long_press_timer.cancel()
            print("[PlayPauseButton] Thread stopped.")

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def _on_long_press_callback(self):
        """Called by the timer when long press duration is reached."""
        print("[PlayPauseButton] Long press detected.")
        self._long_press_triggered = True
        try:
            if self.on_long_press:
                self.on_long_press()
        except Exception as e:
            print("[PlayPauseButton] Error in on_long_press callback:", e)

    def stop(self):
        self._stop_flag = True
        if self._long_press_timer:
            self._long_press_timer.cancel()
