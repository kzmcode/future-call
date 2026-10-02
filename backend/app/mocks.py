"""モデル無しで一連の体験を通すためのモック実装 (architecture.md §3.5)。"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import soundfile as sf

MOCK_TRANSCRIPT = (
    "先月の発表会で、緊張して頭が真っ白になって、最後まで話せませんでした。"
    "みんなの前で失敗してしまって、とても恥ずかしかったです。"
)


@dataclass
class MockVoiceContext:
    mode: str = "standard"


class MockRecognizer:
    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}

    def load(self) -> None:
        return None

    def transcribe(self, wav_path: str) -> str:
        return MOCK_TRANSCRIPT


class MockSynthesizer:
    SR = 24000

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or {}

    def load(self) -> None:
        return None

    def prepare_voice(self, reference_wav, work_dir, median_f0_hz=None) -> MockVoiceContext:
        return MockVoiceContext(mode="clone" if reference_wav else "standard")

    def synthesize(self, ctx, text: str, out_wav: str, style: str | None = None) -> None:
        dur = min(max(0.12 * len(text or " "), 0.3), 12.0)
        n = int(self.SR * dur)
        t = np.arange(n) / self.SR
        f0 = float(self.cfg.get("mock_f0_hz", 180.0))
        vib = 1.0 + 0.03 * np.sin(2 * np.pi * 5 * t)
        x = 0.25 * np.sin(2 * np.pi * f0 * np.cumsum(vib) / self.SR)
        x += 0.1 * np.sin(2 * np.pi * 2 * f0 * np.cumsum(vib) / self.SR)
        x *= 0.6 + 0.4 * np.sin(2 * np.pi * 3 * t) ** 2  # 音節っぽい抑揚
        x += 0.01 * np.random.default_rng(0).standard_normal(n)
        fade = min(int(0.02 * self.SR), n // 2)
        if fade:
            x[:fade] *= np.linspace(0, 1, fade)
            x[-fade:] *= np.linspace(1, 0, fade)
        sf.write(out_wav, x.astype(np.float32), self.SR, subtype="PCM_16")
