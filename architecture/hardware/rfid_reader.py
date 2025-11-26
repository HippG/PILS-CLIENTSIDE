import RPi.GPIO as GPIO
import time
import threading
import spidev
from mfrc522 import SimpleMFRC522


class NFC:
    """
    Adaptation de ta classe NFC pour être utilisée dans un thread.
    """

    def __init__(self, bus=0, device=0, spd=1000000):
        self.reader = SimpleMFRC522()
        self.close()
        self.boards = {}

        self.bus = bus
        self.device = device
        self.spd = spd

    def reinit(self):
        self.reader.READER.spi = spidev.SpiDev()
        self.reader.READER.spi.open(self.bus, self.device)
        self.reader.READER.spi.max_speed_hz = self.spd
        self.reader.READER.MFRC522_Init()

    def close(self):
        try:
            self.reader.READER.spi.close()
        except Exception:
            pass

    def addBoard(self, rid, pin):
        self.boards[rid] = pin
        GPIO.setup(pin, GPIO.OUT)
        print(f"[RFID] Added reader {rid} on GPIO {pin}")

    def selectBoard(self, rid):
        if rid not in self.boards:
            print("[RFID] readerid " + rid + " not found")
            return False

        for loop_id in self.boards:
            GPIO.output(self.boards[loop_id], loop_id == rid)
        time.sleep(0.05)
        return True

    def read(self, rid):
        """Lit un tag RFID sur le lecteur sélectionné et retourne son UID."""
        if not self.selectBoard(rid):
            return None

        self.reinit()
        cid, _ = self.reader.read_no_block()
        self.close()

        if cid:
            return cid
        return None


class RFIDReaderManager:
    """
    Gère plusieurs lecteurs RFID en parallèle (polling rapide) et
    appelle des callbacks lorsqu'un tag est détecté ou retiré.
    """

    def __init__(self, readers, on_tag_detected, on_tag_removed=None):
        """
        readers: liste de tuples (reader_id: str, pin: int)
        on_tag_detected: callback(reader_id: str, tag_id: int)
        on_tag_removed: callback(reader_id: str)
        """
        self.nfc = NFC()
        self.on_tag_detected = on_tag_detected
        self.on_tag_removed = on_tag_removed

        self.readers = [r[0] for r in readers]
        for r_id, pin in readers:
            self.nfc.addBoard(r_id, pin)

        self.last_seen = {r_id: None for r_id in self.readers}
        self._thread = None
        self._stop_flag = False

    def start(self):
        print("[RFID] Starting RFID manager thread.")
        self._stop_flag = False

        def run():
            print("[RFID] Thread started.")
            while not self._stop_flag:
                for r_id in self.readers:
                    try:
                        cid = self.nfc.read(r_id)
                        if cid and cid != self.last_seen[r_id]:
                            print(f"[RFID] {r_id} → new UID detected: {cid}")
                            self.last_seen[r_id] = cid
                            if self.on_tag_detected:
                                try:
                                    self.on_tag_detected(r_id, cid)
                                except Exception as e:
                                    print("[RFID] Error in on_tag_detected callback:", e)
                        elif not cid and self.last_seen[r_id] is not None:
                            removed_cid = self.last_seen[r_id]
                            print(f"[RFID] {r_id} → tag {removed_cid} removed.")
                            self.last_seen[r_id] = None
                            if self.on_tag_removed:
                                try:
                                    self.on_tag_removed(r_id)
                                except Exception as e:
                                    print("[RFID] Error in on_tag_removed callback:", e)
                    except Exception as e:
                        print(f"[RFID] {r_id} error: {e}")
                time.sleep(0.05)

            print("[RFID] Thread stopped.")

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_flag = True
