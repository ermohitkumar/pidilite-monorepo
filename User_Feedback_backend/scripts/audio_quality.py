#!/usr/bin/env python3
"""
audio_quality.py - Pre-screen call recordings before sending them to ASR / LLM processing.

Usage:
    python audio_quality.py call1.webm call2.mp3 --json report.json

Needs: ffmpeg on PATH, numpy, scipy, webrtcvad-wheels   (pip install numpy scipy webrtcvad-wheels)

Output per file: metrics, a 0-100 quality score, a verdict (PASS / REVIEW / REJECT),
reasons, and per-window scores so you can also drop only the bad segments.
"""
import argparse, json, os, re, subprocess, sys
import numpy as np
import webrtcvad
from scipy.signal import stft

SR = 16000
FRAME_MS = 30                      # webrtcvad supports 10/20/30 ms
FRAME = SR * FRAME_MS // 1000
WINDOW_S = 30                      # segment-level scoring window

# ----------------------------------------------------------------- thresholds
# Tune these on a labelled sample of YOUR calls (see README notes in chat).
T = dict(
    snr_good=25, snr_bad=8,                 # dB
    speech_level_good=-26, speech_level_bad=-45,   # dBFS RMS of speech frames
    clip_warn=0.001, clip_bad=0.01,         # fraction of samples at/near full scale
    speech_ratio_min=0.15,                  # below this: mostly silence / dead air
    quiet_speech_bad=0.5,                   # fraction of speech frames < -45 dBFS
    bandwidth_bad=2800,                     # Hz, 95% spectral rolloff of speech
    dropout_good=0.05, dropout_bad=0.40,    # fraction of audio that is digital silence
    spread_good=30, spread_bad=55,          # dB between loud and quiet speech
    pass_score=75, reject_score=45,
)


def load(path):
    """Decode anything ffmpeg understands to 16 kHz mono float32."""
    cmd = ["ffmpeg", "-v", "error", "-i", path, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def db(x, floor=1e-10):
    return 10 * np.log10(np.maximum(x, floor))


def frame_signal(x):
    n = len(x) // FRAME
    return x[: n * FRAME].reshape(n, FRAME)


def vad_flags(x, aggressiveness=2):
    v = webrtcvad.Vad(aggressiveness)
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    n = len(pcm) // FRAME
    flags = np.zeros(n, bool)
    for i in range(n):
        flags[i] = v.is_speech(pcm[i * FRAME:(i + 1) * FRAME].tobytes(), SR)
    # smooth: fill gaps < 300 ms, drop blips < 90 ms
    k = 10
    sm = np.convolve(flags.astype(float), np.ones(k) / k, mode="same") > 0.3
    return sm


def lin(v, bad, good):
    """Map v to 0..1 where `bad` -> 0 and `good` -> 1 (works for either direction)."""
    return float(np.clip((v - bad) / (good - bad), 0, 1))


def analyze_chunk(x, speech_flags=None):
    """Compute metrics for a (sub)signal. Returns dict."""
    frames = frame_signal(x)
    rms = np.sqrt((frames ** 2).mean(1) + 1e-12)
    rms_db = 20 * np.log10(rms)
    live = rms_db > -90                      # frames that actually carry signal (not digital zeros)
    if speech_flags is None:
        speech_flags = vad_flags(x)
    speech_flags = speech_flags[: len(rms)] & live[: len(speech_flags)]
    sp = rms_db[speech_flags]
    ns = rms_db[live & ~speech_flags]
    lv = rms_db[live]

    out = {}
    out["duration_s"] = round(len(x) / SR, 1)
    out["speech_ratio"] = float(speech_flags.mean()) if len(speech_flags) else 0.0
    out["peak_dbfs"] = float(20 * np.log10(np.abs(x).max() + 1e-10))
    out["clipping_ratio"] = float((np.abs(x) >= 0.99).mean())
    # --- dropouts: stretches of exact digital silence (muted mic, lost packets, DTX, recorder gaps)
    out["dropout_ratio"] = float(1 - live.mean())
    d = np.diff(np.r_[0, (~live).astype(int), 0]); runs = (np.where(d == -1)[0] - np.where(d == 1)[0]) * FRAME_MS / 1000
    out["longest_dropout_s"] = float(runs.max()) if len(runs) else 0.0
    out["dropout_count_over_1s"] = int((runs > 1).sum())

    if len(sp) >= 10:
        out["speech_level_dbfs"] = float(np.percentile(sp, 75))      # robust loudness of talking
        out["speech_level_p10_dbfs"] = float(np.percentile(sp, 10))
        out["quiet_speech_ratio"] = float((sp < -45).mean())
        # noise floor = quiet non-speech frames of LIVE audio (never the digital-zero gaps)
        floor = np.percentile(ns, 25) if len(ns) >= 20 else np.percentile(lv, 5)
        out["noise_floor_dbfs"] = float(floor)
        out["snr_db"] = float(min(np.percentile(sp, 75) - floor, 60))
        out["level_spread_db"] = float(np.percentile(sp, 90) - np.percentile(sp, 10))   # volume stability
    else:
        out.update(speech_level_dbfs=-100.0, speech_level_p10_dbfs=-100.0, quiet_speech_ratio=1.0,
                   noise_floor_dbfs=float(np.percentile(lv, 5)) if len(lv) else -120.0, snr_db=0.0, level_spread_db=0.0)

    # spectral features on speech frames only
    f, _, Z = stft(x, SR, nperseg=512, noverlap=256)
    P = np.abs(Z) ** 2                                   # (freq, time)
    t_idx = np.minimum((np.arange(P.shape[1]) * 256) // FRAME, len(speech_flags) - 1)
    sel = speech_flags[t_idx] if len(speech_flags) else np.zeros(P.shape[1], bool)
    if sel.sum() > 10:
        spec = P[:, sel].mean(1)
        cum = np.cumsum(spec) / spec.sum()
        out["rolloff95_hz"] = float(f[np.searchsorted(cum, 0.95)])
        out["hf_ratio_db"] = float(db(spec[f > 4000].sum()) - db(spec[(f > 300) & (f < 3400)].sum()))
        flat = np.exp(np.mean(np.log(P[:, sel] + 1e-12), 0)) / (P[:, sel].mean(0) + 1e-12)
        out["spectral_flatness"] = float(np.median(flat))   # high => noise-like / hiss
    else:
        out.update(rolloff95_hz=0.0, hf_ratio_db=-60.0, spectral_flatness=1.0)
    return out


def score(m):
    """Combine metrics into 0-100 + reasons. Weights reflect 'will ASR be able to read this?'."""
    s = {}
    s["snr"] = lin(m["snr_db"], T["snr_bad"], T["snr_good"])
    s["level"] = lin(m["speech_level_dbfs"], T["speech_level_bad"], T["speech_level_good"])
    s["clipping"] = 1 - lin(m["clipping_ratio"], T["clip_warn"], T["clip_bad"])
    s["quiet_speech"] = 1 - lin(m["quiet_speech_ratio"], 0.1, T["quiet_speech_bad"])
    s["bandwidth"] = lin(m["rolloff95_hz"], T["bandwidth_bad"], 4500)
    s["speech_content"] = lin(m["speech_ratio"], 0.05, T["speech_ratio_min"] * 2)
    s["dropout"] = 1 - lin(m["dropout_ratio"], T["dropout_good"], T["dropout_bad"])
    s["stability"] = 1 - lin(m["level_spread_db"], T["spread_good"], T["spread_bad"])
    w = dict(snr=0.20, level=0.15, clipping=0.10, quiet_speech=0.10, bandwidth=0.05,
             speech_content=0.10, dropout=0.20, stability=0.10)
    total = 100 * sum(s[k] * w[k] for k in w)

    reasons = []
    if m["snr_db"] < T["snr_bad"]: reasons.append(f"Low SNR ({m['snr_db']:.0f} dB) - noisy relative to voice")
    if m["speech_level_dbfs"] < T["speech_level_bad"]: reasons.append(f"Speech very quiet ({m['speech_level_dbfs']:.0f} dBFS)")
    if m["clipping_ratio"] > T["clip_warn"]: reasons.append(f"Clipping/distortion ({m['clipping_ratio']*100:.2f}% samples)")
    if m["quiet_speech_ratio"] > T["quiet_speech_bad"]: reasons.append(f"{m['quiet_speech_ratio']*100:.0f}% of speech is barely audible (< -45 dBFS)")
    if m["level_spread_db"] > T["spread_bad"]: reasons.append(f"Unstable volume ({m['level_spread_db']:.0f} dB spread) - some speakers/moments far quieter")
    if 0 < m["rolloff95_hz"] < T["bandwidth_bad"]: reasons.append(f"Narrow bandwidth ({m['rolloff95_hz']:.0f} Hz) - muffled / telephone-grade")
    if m["dropout_ratio"] > T["dropout_good"]: reasons.append(f"Audio dropouts: {m['dropout_ratio']*100:.0f}% of recording is digital silence (longest {m['longest_dropout_s']:.0f}s)")
    if m["speech_ratio"] < T["speech_ratio_min"]: reasons.append(f"Little speech detected ({m['speech_ratio']*100:.0f}% of audio)")

    # hard gates: any one of these makes the file unusable regardless of average score
    hard_fail = m["speech_ratio"] < 0.03 or m["dropout_ratio"] > 0.6 or m["speech_level_dbfs"] < -55
    verdict = ("REJECT" if hard_fail or total < T["reject_score"]
               else "PASS" if total >= T["pass_score"] and not reasons
               else "REVIEW" if total >= T["reject_score"] else "REJECT")
    if total >= T["pass_score"] and reasons and verdict == "PASS": verdict = "REVIEW"
    return round(total, 1), verdict, reasons, {k: round(v, 2) for k, v in s.items()}


def analyze_file(path):
    x = load(path)
    flags = vad_flags(x)
    m = analyze_chunk(x, flags)
    total, verdict, reasons, sub = score(m)

    # per-window scores -> lets you cut only the bad stretches
    wins, step = [], WINDOW_S * SR
    fpw = WINDOW_S * 1000 // FRAME_MS
    for i in range(0, len(x) - step // 2, step):
        seg = x[i:i + step]
        wm = analyze_chunk(seg, flags[i // FRAME: i // FRAME + fpw])
        ws, wv, _, _ = score(wm)
        wins.append(dict(start_s=i // SR, score=ws, verdict=wv, snr_db=round(wm["snr_db"], 1),
                         speech_level_dbfs=round(wm["speech_level_dbfs"], 1), speech_ratio=round(wm["speech_ratio"], 2), dropout=round(wm["dropout_ratio"], 2)))
    usable = sum(w["verdict"] != "REJECT" and w["speech_ratio"] > 0.1 for w in wins) / max(len(wins), 1)
    name = re.sub(r'^[0-9a-f]{8}-', '', os.path.basename(path))   # drop upload-uuid prefix if present
    return dict(file=path, name=name, score=total, verdict=verdict, reasons=reasons, subscores=sub,
                usable_window_ratio=round(usable, 2),
                metrics={k: round(v, 4) if isinstance(v, float) else v for k, v in m.items()},
                windows=wins)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--json")
    a = ap.parse_args()
    res = [analyze_file(f) for f in a.files]
    for r in res:
        print(f"\n{r['name']}\n  SCORE {r['score']}/100  ->  {r['verdict']}   (usable windows: {r['usable_window_ratio']*100:.0f}%)")
        for k, v in r["metrics"].items(): print(f"    {k:26s} {v}")
        for why in r["reasons"]: print("  !", why)
    if a.json:
        json.dump(res, open(a.json, "w"), indent=2)