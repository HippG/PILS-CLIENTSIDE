from __future__ import annotations
import threading
import time
from typing import Any, Optional, Tuple
from .led_patterns import LedPattern


class LedController:
    """
    Contrôleur LED minimaliste et extensible.
    ------------------------------------------------------------
    - Gère deux patterns actifs :
        * un pattern de fond (background)
        * un pattern temporaire (event)
    - Chaque pattern est une instance de `LedPattern`.
    - Aucun mapping automatique d'état : le contrôleur ne fait
      qu'exécuter les patterns que tu lui demandes.
    """

    _FRAME_INTERVAL = 1.0 / 40.0  # 40 FPS

    def __init__(self, led_driver) -> None:
        self.led_driver = led_driver
        self._pixel_count = getattr(led_driver, "led_count", 0)

        # Patterns actifs
        self._background_pattern: Optional[LedPattern] = None
        self._event_pattern: Optional[LedPattern] = None

        # Synchronisation
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._strip_active = False

        # Thread principal d’animation
        self._loop_thread = threading.Thread(target=self._run_loop, daemon=True)
        self._loop_thread.start()

    # ----------------------------------------------------------
    # Méthodes publiques
    # ----------------------------------------------------------

    def set_background_pattern(
        self,
        pattern: LedPattern | type[LedPattern] | None,
        **params: Any,
    ) -> None:
        """
        Définit ou remplace le pattern de fond.
        - pattern peut être :
            * None → éteint les LEDs
            * une instance de LedPattern
            * une classe de LedPattern (ex: CyclePattern) + paramètres
        """
        with self._lock:
            self._background_pattern = self._build_pattern(pattern, params)

    def led_event(
        self,
        pattern: LedPattern | type[LedPattern] | None,
        **params: Any,
    ) -> None:
        """
        Déclenche un pattern temporaire (flash, etc.)
        - Quand ce pattern est terminé, le fond reprend automatiquement.
        """
        with self._lock:
            self._event_pattern = self._build_pattern(pattern, params)

    def set_group_color(self, group_index: int, color) -> None:
        """Optionnel : pour les patterns supportant des groupes."""
        with self._lock:
            if self._background_pattern and hasattr(self._background_pattern, "set_group_color"):
                try:
                    self._background_pattern.set_group_color(group_index, color)
                except Exception as e:
                    print(f"[LedController] set_group_color error: {e}")

    def clear_group_color(self, group_index: int) -> None:
        """Optionnel : nettoie la couleur d’un groupe."""
        with self._lock:
            if self._background_pattern and hasattr(self._background_pattern, "clear_group_color"):
                try:
                    self._background_pattern.clear_group_color(group_index)
                except Exception as e:
                    print(f"[LedController] clear_group_color error: {e}")

    def clear(self) -> None:
        """Éteint totalement le ruban et efface les patterns."""
        with self._lock:
            self._background_pattern = None
            self._event_pattern = None
        self.led_driver.off()

    def shutdown(self) -> None:
        """Arrête proprement le thread d’animation."""
        self._stop_event.set()
        self._loop_thread.join(timeout=1.5)
        self.led_driver.off()

    # ----------------------------------------------------------
    # Interne
    # ----------------------------------------------------------

    def _build_pattern(
        self,
        pattern: LedPattern | type[LedPattern] | None,
        params: dict[str, Any],
    ) -> Optional[LedPattern]:
        """Instancie ou réinitialise un pattern."""
        if pattern is None:
            return None

        if isinstance(pattern, type) and issubclass(pattern, LedPattern):
            instance = pattern(**params)
        elif isinstance(pattern, LedPattern):
            instance = pattern
        else:
            raise TypeError(f"Invalid pattern type: {type(pattern)}")

        instance.reset(self._pixel_count)
        return instance

    def _run_loop(self) -> None:
        """Boucle principale d’animation : 40 FPS."""
        while not self._stop_event.is_set():
            colors = None
            active_pattern = None

            with self._lock:
                active_pattern = self._event_pattern or self._background_pattern

                if active_pattern:
                    try:
                        colors = active_pattern.render()
                    except Exception as e:
                        print(f"[LedController] render() error: {e}")
                        colors = []

                    # Si l’event pattern est fini → on le retire
                    if self._event_pattern and self._event_pattern.is_finished():
                        self._event_pattern = None

            if colors and len(colors) == self._pixel_count:
                self.led_driver.set_pixels(colors)
                self._strip_active = True
            else:
                if self._strip_active:
                    self.led_driver.off()
                    self._strip_active = False

            time.sleep(self._FRAME_INTERVAL)

        # Nettoyage à la fin
        self.led_driver.off()
        self._strip_active = False
