import time

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

PUMP_PIN = 26
PULSE_DURATION = 1


class PumpRelay:
    """抽水馬達繼電器控制（Active-Low 脈衝切換，BCM 26）。

    與 LightRelay 相同型號繼電器，差異在於自身追蹤 _state，
    呼叫端無需外部管理當前狀態。
    上電初始狀態：馬達 OFF（GPIO HIGH）。
    """

    def __init__(self, pin=PUMP_PIN):
        self.pin = pin
        self._state = 'off'
        if GPIO_AVAILABLE:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(self.pin, GPIO.OUT, initial=GPIO.HIGH)
        else:
            print(f"[Mock] PumpRelay 初始化 pin={self.pin}（無 GPIO，降級為 mock）")

    def _pulse(self):
        if GPIO_AVAILABLE:
            GPIO.output(self.pin, GPIO.LOW)
            time.sleep(PULSE_DURATION)
            GPIO.output(self.pin, GPIO.HIGH)
        else:
            next_state = 'on' if self._state == 'off' else 'off'
            print(f"[Mock] GPIO{self.pin} LOW pulse（狀態 {self._state} → {next_state}）")

    def turn_on(self):
        if self._state != 'on':
            self._pulse()
            self._state = 'on'

    def turn_off(self):
        if self._state != 'off':
            self._pulse()
            self._state = 'off'

    @property
    def is_running(self):
        return self._state == 'on'

    def cleanup(self):
        self.turn_off()
        if GPIO_AVAILABLE:
            GPIO.cleanup(self.pin)
