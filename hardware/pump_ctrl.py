try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

PUMP_PIN = 26
DRAIN_PIN = 20


class PumpRelay:
    """補水馬達繼電器控制（Active-Low 電平，BCM 26）。

    普通繼電器邏輯：
      GPIO HIGH（3.3V）→ 繼電器斷開，馬達停止
      GPIO LOW（GND）  → 繼電器導通，馬達運轉
    上電初始狀態：HIGH，馬達 OFF。
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

    def turn_on(self):
        if self._state != 'on':
            if GPIO_AVAILABLE:
                GPIO.output(self.pin, GPIO.LOW)
            else:
                print(f"[Mock] GPIO{self.pin} → LOW（補水馬達開啟）")
            self._state = 'on'

    def turn_off(self):
        if self._state != 'off':
            if GPIO_AVAILABLE:
                GPIO.output(self.pin, GPIO.HIGH)
            else:
                print(f"[Mock] GPIO{self.pin} → HIGH（補水馬達關閉）")
            self._state = 'off'

    @property
    def is_running(self):
        return self._state == 'on'

    def cleanup(self):
        self.turn_off()
        if GPIO_AVAILABLE:
            GPIO.cleanup(self.pin)


class DrainRelay:
    """抽水繼電器控制（Active-Low 電平，BCM 20）。

    普通繼電器邏輯：
      GPIO HIGH（3.3V）→ 繼電器斷開，抽水馬達停止
      GPIO LOW（GND）  → 繼電器導通，抽水馬達運轉
    上電初始狀態：HIGH，馬達 OFF。
    """

    def __init__(self, pin=DRAIN_PIN):
        self.pin = pin
        self._state = 'off'
        if GPIO_AVAILABLE:
            GPIO.setmode(GPIO.BCM)
            GPIO.setwarnings(False)
            GPIO.setup(self.pin, GPIO.OUT, initial=GPIO.HIGH)
        else:
            print(f"[Mock] DrainRelay 初始化 pin={self.pin}（無 GPIO，降級為 mock）")

    def turn_on(self):
        if self._state != 'on':
            if GPIO_AVAILABLE:
                GPIO.output(self.pin, GPIO.LOW)
            else:
                print(f"[Mock] GPIO{self.pin} → LOW（抽水馬達開啟）")
            self._state = 'on'

    def turn_off(self):
        if self._state != 'off':
            if GPIO_AVAILABLE:
                GPIO.output(self.pin, GPIO.HIGH)
            else:
                print(f"[Mock] GPIO{self.pin} → HIGH（抽水馬達關閉）")
            self._state = 'off'

    @property
    def is_running(self):
        return self._state == 'on'

    def cleanup(self):
        self.turn_off()
        if GPIO_AVAILABLE:
            GPIO.cleanup(self.pin)
