import cv2
import numpy as np


class WaterLevelDetector:
    """以純 OpenCV 偵測魚缸水位。

    場景假設：魚缸正面頂部貼有一條深色遮光膠帶作為目標水位基準線。
    流程：
      1. 取多幀原始 BGR frame，逐列取中值灰階（壓掉魚游動/水波/瞬時反光）。
      2. 在指定 X 區段內，沿頂部找最暗的水平帶（膠帶），取其底緣 row = tape_bottom。
      3. 在 tape_bottom 下方的 ROI 內，用逐列灰階均值的垂直梯度找水面線 = waterline。
      4. gap_px = waterline - tape_bottom（水面在膠帶下方為正）。
      5. gap_px <= gap_threshold_px → 'ok'；超過 → 'low'；找不到水面線 → 'unknown'。
    """

    # 可由 config 調整的參數鍵（供前端調校 UI 使用）
    TUNABLE_KEYS = ('roi_x', 'gap_threshold_px', 'roi_height_ratio',
                    'tape_margin_px', 'frames')

    def __init__(self, camera, roi_x=None, gap_threshold_px=25,
                 tape_bottom_ref=None, frames=8, roi_height_ratio=0.25,
                 tape_margin_px=6):
        self.camera = camera
        self.roi_x = tuple(roi_x) if roi_x else None      # (x1, x2)；None = 全寬
        self.gap_threshold_px = gap_threshold_px
        self.tape_bottom_ref = tape_bottom_ref            # 校正基準（保留供換算）
        self.frames = frames
        self.roi_height_ratio = roi_height_ratio
        # 膠帶底緣本身是強邊；跳過此 margin 後再找水面線，避免誤鎖膠帶邊緣
        self.tape_margin_px = tape_margin_px

    # --- X 區段 ---
    def _x_bounds(self, width):
        """回傳實際分析的 (x1, x2)；roi_x 為 None 則取中間 1/3 避開邊緣造景。"""
        if self.roi_x:
            x1, x2 = self.roi_x
        else:
            x1, x2 = width // 3, width * 2 // 3
        x1 = max(0, min(int(x1), width - 1))
        x2 = max(x1 + 1, min(int(x2), width))
        return x1, x2

    def _x_slice(self, gray):
        x1, x2 = self._x_bounds(gray.shape[1])
        return gray[:, x1:x2]

    # --- 多幀取中值 ---
    def _median_gray(self):
        """連續抓多幀，回傳逐像素中值的灰階影像，失敗回 None。"""
        grays = []
        for _ in range(self.frames):
            frame = self.camera.get_raw_frame()
            if frame is None:
                continue
            grays.append(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
        if not grays:
            return None
        return np.median(np.stack(grays, axis=0), axis=0).astype(np.uint8)

    @staticmethod
    def median_gray_from_frames(frames):
        """由一組已擷取的 BGR frame 算逐像素中值灰階。"""
        grays = [cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames]
        return np.median(np.stack(grays, axis=0), axis=0).astype(np.uint8)

    # --- 偵測核心 ---
    def _find_tape_bottom(self, col):
        """col: (H, W') 灰階區段。找頂部深色膠帶的底緣 row，找不到回 None。"""
        h = col.shape[0]
        row_mean = col.mean(axis=1)
        upper = row_mean[: h // 2]
        dark_thresh = max(40.0, float(row_mean.mean()) - 2.0 * float(row_mean.std()))
        dark_rows = np.where(upper < dark_thresh)[0]
        if dark_rows.size == 0:
            return None
        bottom = dark_rows[0]
        for r in dark_rows:
            if r <= bottom + 3:   # 容忍小斷點
                bottom = r
            else:
                break
        return int(bottom)

    def _find_waterline(self, col, tape_bottom):
        """在 tape_bottom 下方 ROI 內找水面線（最大垂直梯度 row）。
        回傳 (waterline_row, confidence)，找不到回 (None, 0.0)。"""
        h = col.shape[0]
        roi_h = int(h * self.roi_height_ratio)
        top = tape_bottom + self.tape_margin_px
        bottom = min(h, top + roi_h)
        if bottom - top < 5:
            return None, 0.0
        roi = col[top:bottom]
        row_mean = roi.mean(axis=1)
        # 邊緣補值的 3 點移動平均（避免 convolve 'same' 在 ROI 邊界產生假梯度）
        pad = np.pad(row_mean, (1, 1), mode='edge')
        smooth = (pad[:-2] + pad[1:-1] + pad[2:]) / 3.0
        grad = np.abs(np.diff(smooth))
        if grad.size == 0:
            return None, 0.0
        idx = int(np.argmax(grad))
        peak = float(grad[idx])
        mean_grad = float(grad.mean()) + 1e-6
        confidence = min(1.0, peak / (mean_grad * 6.0))
        return int(top + idx), round(confidence, 3)

    def _percent_from_gap(self, gap_px):
        """gap=0（水面齊膠帶底）→ 100%；gap 達 2 倍門檻 → 0%。"""
        span = max(1.0, self.gap_threshold_px * 2.0)
        pct = (1.0 - gap_px / span) * 100.0
        return int(max(0, min(100, round(pct))))

    def _analyze(self, gray):
        """對一張灰階影像執行完整偵測，回傳結果 dict。"""
        col = self._x_slice(gray)
        tape_bottom = self._find_tape_bottom(col)
        if tape_bottom is None:
            return {"state": "unknown", "reason": "no_tape",
                    "gap_px": None, "percent": None,
                    "tape_bottom": None, "waterline": None, "confidence": 0.0}
        waterline, confidence = self._find_waterline(col, tape_bottom)
        if waterline is None:
            return {"state": "unknown", "reason": "no_waterline",
                    "gap_px": None, "percent": None,
                    "tape_bottom": int(tape_bottom), "waterline": None,
                    "confidence": 0.0}
        gap_px = waterline - tape_bottom
        state = "ok" if gap_px <= self.gap_threshold_px else "low"
        return {
            "state": state,
            "gap_px": int(gap_px),
            "percent": self._percent_from_gap(gap_px),
            "tape_bottom": int(tape_bottom),
            "waterline": int(waterline),
            "confidence": confidence,
            "reason": None,
        }

    # --- 對外 API ---
    def detect(self):
        """即時擷取多幀並偵測。"""
        gray = self._median_gray()
        if gray is None:
            return {"state": "unknown", "reason": "no_frame",
                    "gap_px": None, "percent": None}
        return self._analyze(gray)

    def analyze_frames(self, frames):
        """對一組已擷取的 BGR frame 偵測（供調校時對固定幀重複分析）。"""
        if not frames:
            return {"state": "unknown", "reason": "no_frame",
                    "gap_px": None, "percent": None}
        return self._analyze(self.median_gray_from_frames(frames))

    def detect_from_image(self, gray_or_bgr):
        """測試用：直接餵一張影像（BGR 或灰階 numpy）。"""
        gray = cv2.cvtColor(gray_or_bgr, cv2.COLOR_BGR2GRAY) if gray_or_bgr.ndim == 3 else gray_or_bgr
        return self._analyze(gray)

    def calibrate(self):
        """在目前（正確）水位下擷取一幀，回傳建議基準值。"""
        gray = self._median_gray()
        if gray is None:
            return {"ok": False, "reason": "no_frame"}
        res = self._analyze(gray)
        if res.get("tape_bottom") is None:
            return {"ok": False, "reason": res.get("reason", "no_tape")}
        return {
            "ok": True,
            "tape_bottom_ref": res["tape_bottom"],
            "waterline": res.get("waterline"),
            "suggested_gap_threshold_px": self.gap_threshold_px,
            "confidence": res.get("confidence", 0.0),
        }

    def annotate(self, bgr_frame, result):
        """在 BGR frame 上畫出膠帶底緣、容許門檻、水面線與分析 X 區段。回傳新影像。"""
        img = bgr_frame.copy()
        h, w = img.shape[:2]
        x1, x2 = self._x_bounds(w)

        # 分析 X 區段（淺藍垂直邊界）
        cv2.line(img, (x1, 0), (x1, h), (255, 200, 0), 1)
        cv2.line(img, (x2, 0), (x2, h), (255, 200, 0), 1)

        tape = result.get("tape_bottom")
        if tape is not None:
            cv2.line(img, (x1, tape), (x2, tape), (0, 255, 255), 2)  # 黃：膠帶底
            cv2.putText(img, "TAPE", (x1 + 4, max(14, tape - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
            # 容許門檻線（膠帶底 + gap_threshold_px，橘色）
            limit = tape + self.gap_threshold_px
            if 0 <= limit < h:
                cv2.line(img, (x1, limit), (x2, limit), (0, 165, 255), 1)
                cv2.putText(img, "LIMIT", (x1 + 4, min(h - 4, limit + 14)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 165, 255), 1, cv2.LINE_AA)

        water = result.get("waterline")
        if water is not None:
            color = (0, 200, 0) if result.get("state") == "ok" else (0, 0, 255)
            cv2.line(img, (x1, water), (x2, water), color, 2)  # 綠/紅：水面
            cv2.putText(img, "WATER", (x1 + 4, min(h - 4, water + 16)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        return img
