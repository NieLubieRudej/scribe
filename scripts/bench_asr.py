"""ASR reliability benchmark on THIS machine (gate G4).

Downloads a real YouTube English video's audio, runs Parakeet-mlx 3× over a fixed
window, and reports RTF (mean ± SE) and a rough WER against the video's manual
caption track as a pseudo-reference. Also checks language routing (supports()).

Usage:  uv run python scripts/bench_asr.py [VIDEO_ID] [WINDOW_SECONDS]
"""

from __future__ import annotations

import statistics
import subprocess
import sys
import time
from pathlib import Path

from scribe import captions as cap
from scribe.asr.parakeet import ParakeetMLX
from scribe.models import VideoMeta
from scribe.sources.youtube import YouTubeSource

TMP = Path("/private/tmp/claude-504/-Users-kbtest/0601ce46-cf61-454f-896c-a7b2f28007e3/scratchpad/asr_bench")


def _norm(s: str) -> list[str]:
    import re

    return re.sub(r"[^\w\s]", " ", s.lower()).split()


def wer(ref: str, hyp: str) -> float:
    r, h = _norm(ref), _norm(hyp)
    if not r:
        return float("nan")
    # word-level Levenshtein
    dp = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, len(h) + 1):
            cur = dp[j]
            dp[j] = min(dp[j] + 1, dp[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev = cur
    return dp[len(h)] / len(r)


def main() -> None:
    vid = sys.argv[1] if len(sys.argv) > 1 else "mvcesPWvUIc"
    window = float(sys.argv[2]) if len(sys.argv) > 2 else 180.0
    TMP.mkdir(parents=True, exist_ok=True)

    src = YouTubeSource()
    v = VideoMeta(id=vid, title="?", url=f"https://www.youtube.com/watch?v={vid}")

    print(f"# bench {vid}  window={window}s")
    t0 = time.perf_counter()
    full = src.download_audio(v, str(TMP))
    print(f"download+wav: {time.perf_counter() - t0:.1f}s -> {full}")

    import soundfile as sf

    info = sf.info(full)
    print(f"wav: {info.samplerate} Hz, {info.channels} ch, {info.frames / info.samplerate:.0f}s")
    assert info.samplerate == 16000 and info.channels == 1, "wav not 16k mono!"

    bench = TMP / "bench.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", full, "-t", str(window),
         "-ar", "16000", "-ac", "1", str(bench)],
        check=True,
    )

    asr = ParakeetMLX()
    t0 = time.perf_counter()
    asr._load()
    print(f"model load (one-time, incl. download if first run): {time.perf_counter() - t0:.1f}s")

    # warmup (excluded), then 3 timed seeds
    _ = asr.transcribe(str(bench))
    rtfs, hyp = [], ""
    for i in range(3):
        t0 = time.perf_counter()
        res = asr.transcribe(str(bench))
        dt = time.perf_counter() - t0
        rtfs.append(dt / window)
        hyp = res.text
        print(f"  seed {i + 1}: {dt:.2f}s  RTF={dt / window:.3f}  (~{window / dt:.1f}x realtime)")

    mean = statistics.mean(rtfs)
    se = statistics.stdev(rtfs) / (len(rtfs) ** 0.5)
    print(f"RTF mean={mean:.3f} ± {se:.3f} SE  (~{1 / mean:.1f}x realtime)")

    # reference: manual captions for [0, window)
    c = src.fetch_captions(v, None)
    ref = ""
    if c and c.is_manual:
        ref = cap.build_full_text([s for s in c.segments if s.start < window])
        print(f"WER vs manual caption [{0}-{int(window)}s]: {wer(ref, hyp):.3f}")
    else:
        print("WER: no manual caption available as reference (skipped)")
    print(f"hyp sample : {hyp[:160]!r}")
    print(f"ref sample : {ref[:160]!r}")

    print("\nrouting: supports('en')=%s supports('pl')=%s supports(None)=%s"
          % (asr.supports("en"), asr.supports("pl"), asr.supports(None)))


if __name__ == "__main__":
    main()
