#!/usr/bin/env python3
import time
import threading
import subprocess
import board
import neopixel

# -------------------------
# CONFIGURATION
# -------------------------
LED_PIN = board.D13       # ✅ GPIO13 (PWM1)
LED_COUNT = 30
BRIGHTNESS = 0.4
AUDIO_FILE = "epic.mp3"  # ton fichier audio

# -------------------------
# CLASSE LED
# -------------------------
class LedDriver:
    def __init__(self, pin=LED_PIN, count=LED_COUNT, brightness=BRIGHTNESS):
        self.lock = threading.Lock()
        self.pixels = neopixel.NeoPixel(
            pin,
            count,
            brightness=brightness,
            auto_write=False,
            pixel_order=neopixel.GRB
        )
        self.running = False

    def set_color(self, r, g, b):
        with self.lock:
            for i in range(len(self.pixels)):
                self.pixels[i] = (r, g, b)
            self.pixels.show()

    def off(self):
        self.set_color(0, 0, 0)

    def start_pattern(self):
        """Démarre une boucle d’animation dans un thread séparé."""
        if self.running:
            return
        self.running = True

        def run():
            colors = [
                (255, 0, 0),   # rouge
                (0, 255, 0),   # vert
                (0, 0, 255),   # bleu
                (255, 255, 0), # jaune
                (255, 0, 255), # magenta
                (0, 255, 255)  # cyan
            ]
            i = 0
            print("💡 Thread LEDs démarré.")
            while self.running:
                r, g, b = colors[i % len(colors)]
                self.set_color(r, g, b)
                i += 1
                time.sleep(0.5)
            self.off()
            print("💡 Thread LEDs arrêté.")

        t = threading.Thread(target=run, daemon=True)
        t.start()

    def stop_pattern(self):
        self.running = False


# -------------------------
# LECTURE AUDIO
# -------------------------
def play_audio(file_path):
    """Lance mpg123 dans un sous-processus."""
    print(f"🎵 Lecture de {file_path} ...")
    try:
        subprocess.run(["mpg123", "-q", file_path], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Erreur mpg123: {e}")
    except FileNotFoundError:
        print("❌ mpg123 non trouvé, installe-le avec : sudo apt install mpg123")


# -------------------------
# MAIN
# -------------------------
def main():
    leds = LedDriver()
    leds.start_pattern()

    # Lancer l’audio dans un thread pour ne pas bloquer
    audio_thread = threading.Thread(target=play_audio, args=(AUDIO_FILE,))
    audio_thread.start()

    # Pendant que l’audio joue, attendre qu’il se termine
    audio_thread.join()

    # Couper les LEDs
    leds.stop_pattern()
    time.sleep(0.5)
    leds.off()

    print("✅ Audio et LEDs terminés.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n🛑 Interrompu par l'utilisateur.")
