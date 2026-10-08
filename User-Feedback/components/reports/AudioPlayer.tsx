"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { LuPause, LuPlay, LuRotateCcw, LuRotateCw } from "react-icons/lu";

import { ReportModal } from "@/components/reports/ReportModal";

function formatTime(seconds: number): string {
    if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
    const whole = Math.floor(seconds);
    const hours = Math.floor(whole / 3600);
    const minutes = Math.floor((whole % 3600) / 60);
    const rest = whole % 60;
    if (hours > 0) {
        return `${hours}:${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
    }
    return `${minutes}:${String(rest).padStart(2, "0")}`;
}

function finiteDuration(value: number): number {
    return Number.isFinite(value) && value > 0 ? value : 0;
}

function readMediaDuration(node: HTMLMediaElement): number {
    const direct = finiteDuration(node.duration);
    if (direct > 0) return direct;
    try {
        if (node.seekable && node.seekable.length > 0) {
            return finiteDuration(node.seekable.end(node.seekable.length - 1));
        }
    } catch {
        /* seekable can throw before enough data */
    }
    return 0;
}

/**
 * Chrome MediaRecorder WebM often reports duration=Infinity until the end is
 * visited. Seeking far ahead forces the browser to clamp to the real length.
 */
function discoverMediaDuration(
    node: HTMLMediaElement,
    onFound: (seconds: number) => void,
): () => void {
    let cancelled = false;
    let probing = false;

    const finish = (seconds: number) => {
        if (cancelled || !(seconds > 0)) return;
        onFound(seconds);
    };

    const tryRead = () => {
        const d = readMediaDuration(node);
        if (d > 0) finish(d);
        return d > 0;
    };

    const probeInfinity = () => {
        if (cancelled || probing) return;
        if (Number.isFinite(node.duration) && node.duration > 0) {
            finish(node.duration);
            return;
        }
        if (tryRead()) return;

        probing = true;
        const resumeAt = node.currentTime || 0;
        const wasPaused = node.paused;

        const cleanup = () => {
            node.removeEventListener("timeupdate", onSeekProbe);
            node.removeEventListener("seeked", onSeekProbe);
            probing = false;
        };

        const onSeekProbe = () => {
            const d = readMediaDuration(node);
            // After seeking past EOF, currentTime clamps to the real end.
            const clamped = finiteDuration(node.currentTime);
            const found = d > 0 ? d : clamped;
            if (!(found > 0)) return;
            cleanup();
            try {
                node.currentTime = resumeAt;
            } catch {
                /* ignore */
            }
            if (!wasPaused) void node.play().catch(() => undefined);
            finish(found);
        };

        node.addEventListener("timeupdate", onSeekProbe);
        node.addEventListener("seeked", onSeekProbe);
        try {
            node.currentTime = 1e101;
        } catch {
            cleanup();
        }
    };

    if (!tryRead()) {
        // Metadata may arrive late; also kick the Infinity seek once ready.
        const onMeta = () => {
            if (!tryRead()) probeInfinity();
        };
        node.addEventListener("loadedmetadata", onMeta);
        node.addEventListener("durationchange", onMeta);
        if (node.readyState >= 1) onMeta();
        return () => {
            cancelled = true;
            node.removeEventListener("loadedmetadata", onMeta);
            node.removeEventListener("durationchange", onMeta);
        };
    }

    return () => {
        cancelled = true;
    };
}

function AudioPlaybackModal({
    jobId,
    fileName,
    onClose,
    onDurationResolved,
}: Readonly<{
    jobId: string;
    fileName?: string;
    onClose: () => void;
    onDurationResolved?: (seconds: number) => void;
}>) {
    const audioRef = useRef<HTMLAudioElement | null>(null);
    const scrubbingRef = useRef(false);
    const measuredRef = useRef(false);
    const [playing, setPlaying] = useState(false);
    const [current, setCurrent] = useState(0);
    const [measuredDuration, setMeasuredDuration] = useState(0);
    const [error, setError] = useState<string | null>(null);
    const [ready, setReady] = useState(false);
    const src = `/bff/reports/audio/${encodeURIComponent(jobId)}`;
    // Play page: only show media-measured length. Do not use DB estimates here —
    // WebM size/bitrate values often disagree with playable length.
    const total =
        measuredDuration > 0 ? measuredDuration : finiteDuration(current);

    const publishMeasured = useCallback(
        (seconds: number) => {
            if (!(seconds > 0)) return;
            measuredRef.current = true;
            setMeasuredDuration(seconds);
            onDurationResolved?.(seconds);
        },
        [onDurationResolved],
    );

    const readError = useCallback(async () => {
        try {
            const res = await fetch(src, {
                method: "GET",
                cache: "no-store",
                headers: { Range: "bytes=0-1" },
            });
            if (res.ok || res.status === 206) return;
            const json = (await res.json().catch(() => null)) as { error?: string } | null;
            setError(json?.error || `Could not load this recording (${res.status}).`);
        } catch {
            setError("Could not load this recording.");
        }
    }, [src]);

    const seekTo = useCallback((next: number) => {
        const node = audioRef.current;
        const capped = Math.min(Math.max(next, 0), total > 0 ? total : next);
        if (node) {
            try {
                node.currentTime = capped;
            } catch {
                /* some browsers reject seek before enough data */
            }
        }
        setCurrent(capped);
    }, [total]);

    const seekBy = useCallback((delta: number) => {
        const node = audioRef.current;
        const base = node?.currentTime ?? current;
        seekTo(base + delta);
    }, [current, seekTo]);

    const toggle = useCallback(() => {
        const node = audioRef.current;
        if (!node || error) return;
        if (node.paused) void node.play().catch(() => undefined);
        else node.pause();
    }, [error]);

    useEffect(() => {
        const node = audioRef.current;
        if (!node) return;

        const syncDuration = () => {
            const d = readMediaDuration(node);
            if (d > 0) publishMeasured(d);
        };
        const onTime = () => {
            const t = node.currentTime || 0;
            if (!scrubbingRef.current) setCurrent(t);
            if (!measuredRef.current && Number.isFinite(node.duration) && node.duration > 0) {
                publishMeasured(node.duration);
            }
        };
        const onPlay = () => setPlaying(true);
        const onPause = () => setPlaying(false);
        const onEnded = () => {
            setPlaying(false);
            // Real playable length only — never blend in a DB estimate.
            const measured = Math.max(readMediaDuration(node), node.currentTime || 0);
            if (measured > 0) {
                publishMeasured(measured);
                setCurrent(measured);
            }
        };
        const onReady = () => {
            setReady(true);
            syncDuration();
        };
        const onError = () => {
            setPlaying(false);
            setError("Could not play this recording.");
            void readError();
        };

        const stopDiscover = discoverMediaDuration(node, publishMeasured);

        node.addEventListener("timeupdate", onTime);
        node.addEventListener("durationchange", syncDuration);
        node.addEventListener("loadedmetadata", onReady);
        node.addEventListener("loadeddata", onReady);
        node.addEventListener("canplay", onReady);
        node.addEventListener("play", onPlay);
        node.addEventListener("pause", onPause);
        node.addEventListener("ended", onEnded);
        node.addEventListener("error", onError);

        node.load();
        const playAttempt = node.play();
        if (playAttempt) playAttempt.catch(() => undefined);

        return () => {
            stopDiscover();
            node.pause();
            node.removeEventListener("timeupdate", onTime);
            node.removeEventListener("durationchange", syncDuration);
            node.removeEventListener("loadedmetadata", onReady);
            node.removeEventListener("loadeddata", onReady);
            node.removeEventListener("canplay", onReady);
            node.removeEventListener("play", onPlay);
            node.removeEventListener("pause", onPause);
            node.removeEventListener("ended", onEnded);
            node.removeEventListener("error", onError);
        };
    }, [publishMeasured, readError]);

    useEffect(() => {
        const onKey = (event: KeyboardEvent) => {
            const target = event.target as HTMLElement | null;
            if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
                return;
            }
            if (event.key === "ArrowLeft") {
                event.preventDefault();
                seekBy(-10);
            } else if (event.key === "ArrowRight") {
                event.preventDefault();
                seekBy(10);
            } else if (event.key === " ") {
                event.preventDefault();
                toggle();
            }
        };
        window.addEventListener("keydown", onKey);
        return () => window.removeEventListener("keydown", onKey);
    }, [seekBy, toggle]);

    const scrubMax = measuredDuration > 0 ? measuredDuration : Math.max(current, 1);
    const scrubValue = Math.min(current, scrubMax);
    const progressPct =
        measuredDuration > 0 ? Math.min(100, (current / measuredDuration) * 100) : 0;

    return (
        <ReportModal
            open
            title="Call recording"
            subtitle={fileName || undefined}
            onClose={onClose}
        >
            {error ? (
                <p className="text-sm text-status-red-fg">{error}</p>
            ) : (
                <div className="space-y-5">
                    <audio
                        ref={audioRef}
                        src={src}
                        preload="auto"
                        autoPlay
                        className="hidden"
                        aria-hidden
                    >
                        Your browser does not support audio playback.
                    </audio>

                    <div className="rounded-xl border border-border bg-surface-raised px-4 py-5">
                        <div className="mb-3 flex items-end justify-between gap-3 tabular-nums">
                            <div>
                                <p className="text-[11px] font-semibold uppercase tracking-wide text-text-subtle">
                                    Current
                                </p>
                                <p className="mt-0.5 text-2xl font-semibold text-text">
                                    {formatTime(current)}
                                </p>
                            </div>
                            <div className="text-right">
                                <p className="text-[11px] font-semibold uppercase tracking-wide text-text-subtle">
                                    Duration
                                </p>
                                <p className="mt-0.5 text-2xl font-semibold text-text">
                                    {measuredDuration > 0
                                        ? formatTime(measuredDuration)
                                        : ready
                                          ? "…"
                                          : "—"}
                                </p>
                            </div>
                        </div>

                        <div className="relative">
                            <div className="pointer-events-none absolute inset-y-0 left-0 right-0 flex items-center">
                                <div className="h-1.5 w-full overflow-hidden rounded-full bg-border">
                                    <div
                                        className="h-full rounded-full bg-brand"
                                        style={{ width: `${progressPct}%` }}
                                    />
                                </div>
                            </div>
                            <input
                                type="range"
                                min={0}
                                max={scrubMax}
                                step={0.1}
                                value={scrubValue}
                                disabled={measuredDuration <= 0 && !ready}
                                onPointerDown={() => {
                                    scrubbingRef.current = true;
                                }}
                                onPointerUp={() => {
                                    scrubbingRef.current = false;
                                }}
                                onChange={(event) => {
                                    const next = Number(event.target.value);
                                    setCurrent(next);
                                    seekTo(next);
                                }}
                                className="relative z-10 h-6 w-full cursor-pointer appearance-none bg-transparent accent-brand disabled:cursor-not-allowed"
                                aria-label="Seek to timestamp"
                                aria-valuemin={0}
                                aria-valuemax={Math.round(scrubMax)}
                                aria-valuenow={Math.round(scrubValue)}
                                aria-valuetext={`${formatTime(scrubValue)} of ${measuredDuration > 0 ? formatTime(measuredDuration) : "unknown"}`}
                            />
                        </div>

                        <div className="mt-1 flex justify-between text-[11px] tabular-nums text-text-subtle">
                            <span>{formatTime(0)}</span>
                            <span>
                                {measuredDuration > 0
                                    ? formatTime(measuredDuration)
                                    : "measuring duration…"}
                            </span>
                        </div>
                    </div>

                    <div className="flex items-center justify-center gap-3">
                        <button
                            type="button"
                            onClick={() => seekBy(-10)}
                            className="inline-flex items-center gap-1.5 rounded-full border border-border px-3.5 py-2.5 text-xs font-semibold text-text hover:bg-surface-raised"
                            aria-label="Back 10 seconds"
                        >
                            <LuRotateCcw className="h-4 w-4" />
                            −10s
                        </button>
                        <button
                            type="button"
                            onClick={toggle}
                            className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-brand text-white shadow-sm hover:opacity-90"
                            aria-label={playing ? "Pause" : "Play"}
                        >
                            {playing ? (
                                <LuPause className="h-6 w-6" />
                            ) : (
                                <LuPlay className="ml-0.5 h-6 w-6" />
                            )}
                        </button>
                        <button
                            type="button"
                            onClick={() => seekBy(10)}
                            className="inline-flex items-center gap-1.5 rounded-full border border-border px-3.5 py-2.5 text-xs font-semibold text-text hover:bg-surface-raised"
                            aria-label="Forward 10 seconds"
                        >
                            +10s
                            <LuRotateCw className="h-4 w-4" />
                        </button>
                    </div>

                    <p className="text-center text-xs text-text-subtle">
                        Drag the timeline to jump. ← / → skip 10s · Space plays or pauses.
                    </p>
                </div>
            )}
        </ReportModal>
    );
}

export function AudioPlayer({
    jobId,
    fileName,
    durationSeconds,
    onDurationResolved,
}: Readonly<{
    jobId?: string;
    fileName?: string;
    durationSeconds?: number | null;
    onDurationResolved?: (seconds: number) => void;
}>) {
    const [open, setOpen] = useState(false);
    const [playableSeconds, setPlayableSeconds] = useState(0);
    const probeRef = useRef<HTMLAudioElement | null>(null);

    const handleResolved = useCallback(
        (seconds: number) => {
            if (!(seconds > 0)) return;
            // Authoritative media length replaces any prior estimate.
            setPlayableSeconds(seconds);
            onDurationResolved?.(seconds);
        },
        [onDurationResolved],
    );

    useEffect(() => {
        if (!jobId) return;
        const node = probeRef.current;
        if (!node) return;

        const stop = discoverMediaDuration(node, handleResolved);
        node.load();

        return () => {
            stop();
        };
    }, [handleResolved, jobId]);

    if (!jobId) {
        return <span className="text-text-subtle">—</span>;
    }

    const src = `/bff/reports/audio/${encodeURIComponent(jobId)}`;
    const knownDb =
        durationSeconds != null && Number.isFinite(durationSeconds) && durationSeconds > 0
            ? durationSeconds
            : 0;
    // Prefer measured playable length for the Play label once known.
    const labelSeconds = playableSeconds > 0 ? playableSeconds : knownDb;
    const known = labelSeconds > 0 ? formatTime(labelSeconds) : null;

    return (
        <>
            <audio
                ref={probeRef}
                src={src}
                preload="auto"
                className="hidden"
                aria-hidden
            />
            <button
                type="button"
                onClick={() => setOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-full bg-brand-subtle px-2.5 py-1 text-xs font-semibold text-brand hover:bg-brand hover:text-white"
            >
                <LuPlay className="h-3.5 w-3.5" />
                Play{known ? ` · ${known}` : ""}
            </button>
            {open ? (
                <AudioPlaybackModal
                    jobId={jobId}
                    fileName={fileName}
                    onClose={() => setOpen(false)}
                    onDurationResolved={handleResolved}
                />
            ) : null}
        </>
    );
}
