import time

try:
    import RPi.GPIO as GPIO
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

# BCM GPIO 16（實體腳位 36）
# NPN 輸出：水位正常 → LOW；水位過低 → HIGH
SENSOR_PIN = 16

# 防抖：讀取 N 次，全部一致才回傳，避免水面波動造成誤報
_DEBOUNCE_READS   = 5
_DEBOUNCE_DELAY_S = 0.05


class WaterLevelSensor:
    """才嘉科技外貼式非接觸液位感測器（NPN 輸出，DC 5-12V）。

    NPN 邏輯：
      - 感測面偵測到液體 → 輸出 LOW  → 水位正常
      - 感測面無液體     → 輸出 HIGH → 水位過低

    Pin 腳接法（BCM）：
      VCC  → 5V（實體腳位 2 或 4）
      GND  → GND（實體腳位 6）
      OUT  → GPIO 16（實體腳位 36），加 10kΩ 下拉電阻接 GND
    """

    def __init__(self, pin=SENSOR_PIN):
        self.pin = pin
        if GPIO_AVAILABLE:
            GPIO.setwarnings(False)
            GPIO.setmode(GPIO.BCM)
            # 使用內建下拉；若外部已接 10kΩ 下拉可改 GPIO.PUD_OFF
            GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
        else:
            print(f"[Mock] WaterLevelSensor 初始化 pin={self.pin}（無 GPIO，降級為 mock）")

    def read_raw(self):
        """讀一次原始訊號，回傳 True（HIGH = 過低）或 False（LOW = 正常）。
        無 GPIO 時固定回傳 False（模擬正常）。"""
        if not GPIO_AVAILABLE:
            return False
        return bool(GPIO.input(self.pin))

    def is_low(self):
        """防抖讀取：連續 N 次訊號一致才確認結果。
        回傳 True = 水位過低，False = 水位正常。"""
        if not GPIO_AVAILABLE:
            return False
        results = []
        for _ in range(_DEBOUNCE_READS):
            results.append(bool(GPIO.input(self.pin)))
            time.sleep(_DEBOUNCE_DELAY_S)
        # 多數決（超過一半為 HIGH 視為過低）
        return results.count(True) > len(results) // 2

    def state(self):
        """回傳結果 dict，供 API 直接序列化。"""
        low = self.is_low()
        return {
            "sensor_triggered": low,
            "state": "low" if low else "ok",
        }

    def cleanup(self):
        if GPIO_AVAILABLE:
            GPIO.cleanup(self.pin)
