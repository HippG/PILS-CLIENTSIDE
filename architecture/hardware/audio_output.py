import subprocess
import math

class AudioOutput:
    """
    Gestion du volume réel via ALSA (WM8960) avec échelle psychoacoustique logarithmique.
    """

    def __init__(self, initial_volume: float = 0.5):
        self.volume = initial_volume
        self._apply_volume()
        print(f"[AudioOutput] Initialized with perceptual volume={self.volume:.2f}")

    def _volume_curve(self, x: float) -> int:
        """
        Convertit volume [0.0–1.0] en valeur ALSA [0–127]
        avec une courbe psychoacoustique (log).
        """

        # Plage utile empirique : ~70–95 % du WM8960
        min_val, max_val = 60, 123  # éviter la zone inaudible et la saturation

        # Courbe logarithmique adoucie
        perceptual = math.pow(x, 0.3)  # 0.3 ≈ plus de contrôle en bas, plus doux en haut

        val = int(min_val + (max_val - min_val) * perceptual)
        return max(0, min(127, val))

    def _apply_volume(self):
        alsa_val = self._volume_curve(self.volume)
        try:
            subprocess.run(
                ["amixer", "set", "Speaker", f"{alsa_val},{alsa_val}"],
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as e:
            print("[AudioOutput] ⚠️ Erreur lors de l'application du volume hardware:")
            print(e.stderr.decode())

    def set_volume(self, value: float):
        self.volume = round(max(0.0, min(1.0, value)), 2)
        print(f"[AudioOutput] Logical volume set to {self.volume:.2f}")
        self._apply_volume()
