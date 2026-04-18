import time

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

RELAY_PIN = 12
PULSE_DURATION = 0.1  # 100ms 脈衝


class LightRelay:
    def __init__(self, pin=RELAY_PIN):
        self.pin = pin
        if GPIO_AVAILABLE:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(self.pin, GPIO.OUT, initial=GPIO.LOW)

    def _pulse(self):
        """送一次脈衝切換繼電器狀態"""
        if GPIO_AVAILABLE:
            GPIO.output(self.pin, GPIO.HIGH)
            time.sleep(PULSE_DURATION)
            GPIO.output(self.pin, GPIO.LOW)
        else:
            print(f"[Mock] GPIO{self.pin} pulse")

    def set_state(self, current_state: str, target_state: str):
        """只在狀態需要改變時送脈衝"""
        if current_state != target_state:
            self._pulse()

    def cleanup(self):
        if GPIO_AVAILABLE:
            GPIO.cleanup(self.pin)
