"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { LuPause, LuPlay, LuRotateCcw, LuRotateCw } from "react-icons/lu";

import { ReportModal } from "@/components/reports/ReportModal";

function formatTime(seconds: number): string {
    if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
    const whole = Math.floor(seconds);
    const minutes = Math.floor(whole / 60);
    const rest = whole % 60;
    return `${minutes}:${String(rest).padStart(2, "0")}`;
}

function AudioPlaybackModal({
    jobId,
    fileName,
    onClose,
}: Readonly<{
    jobId: string;
    fileName?: string;
    onClose: () => void;
}>) {
    const audioRef = useRef<HTMLAudioElement | null>(null);
    const [playing, setPlaying] = useState(false);
    const [current, setCurrent] = useState(0);
    const [duration, setDuration] = useState(0);
    const [error, setError] = useState<string | null>(null);
    const src = `/api/reports/audio/${encodeURIComponent(jobId)}`;

    const readError = useCallback(async () => {
        try {
            const res = await fetch(src, {
                method: "GET",
                cache: "no-store",
                headers: { Range: "bytes=0-1" },
            });
            if (res.ok) return;
            const json = (await res.json().catch(() => null)) as { error?: string } | null;
            setError(json?.error || `Could not load this recording (${res.status}).`);
        } catch {
            setError("Could not load this recording.");
        }
    }, [src]);

    useEffect(() => {
        const node = audioRef.current;
        if (!node) return;

        const onTime = () => setCurrent(node.currentTime || 0);
        const onMeta = () => setDuration(node.duration || 0);
        const onPlay = () => setPlaying(true);
        const onPause = () => setPlaying(false);
        const onEnded = () => setPlaying(false);
        const onError = () => {
            setPlaying(false);
            setError("Could not play this recording.");
            void readError();
        };

        node.addEventListener("timeupdate", onTime);
        node.addEventListener("durationchange", onMeta);
        node.addEventListener("loadedmetadata", onMeta);
        node.addEventListener("play", onPlay);
        node.addEventListener("pause", onPause);
        node.addEventListener("ended", onEnded);
        node.addEventListener("error", onError);
        const playAttempt = node.play();
        if (playAttempt) playAttempt.catch(() => undefined);

        return () => {
            node.pause();
            node.removeEventListener("timeupdate", onTime);
            node.removeEventListener("durationchange", onMeta);
            node.removeEventListener("loadedmetadata", onMeta);
            node.removeEventListener("play", onPlay);
            node.removeEventListener("pause", onPause);
            node.removeEventListener("ended", onEnded);
            node.removeEventListener("error", onError);
        };
    }, [readError]);

    const seekBy = (delta: number) => {
        const node = audioRef.current;
        if (!node) return;
        const next = Math.min(Math.max((node.currentTime || 0) + delta, 0), duration || node.duration || 0);
        node.currentTime = next;
        setCurrent(next);
    };

    const toggle = () => {
        const node = audioRef.current;
        if (!node) return;
        if (node.paused) void node.play();
        else node.pause();
    };

    useEffect(() => {
        const onKey = (event: KeyboardEvent) => {
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
    });

    const max = duration > 0 && Number.isFinite(duration) ? duration : 0;

    return (
        <ReportModal
            open
            title="Call recording"
            subtitle={fileName || undefined}
            onClose={onClose}
        >
            {error ? (
                <p className="text-sm text-red-600">{error}</p>
            ) : (
                <div className="space-y-4">
                    <audio
                        ref={audioRef}
                        src={src}
                        controls
                        autoPlay
                        preload="auto"
                        className="w-full"
                    >
                        Your browser does not support audio playback.
                    </audio>
                    <input
                        type="range"
                        min={0}
                        max={max || 0}
                        step={0.1}
                        value={Math.min(current, max || current)}
                        disabled={max <= 0}
                        onChange={(event) => {
                            const next = Number(event.target.value);
                            const node = audioRef.current;
                            if (node) node.currentTime = next;
                            setCurrent(next);
                        }}
                        className="h-2 w-full cursor-pointer accent-brand"
                        aria-label="Seek"
                    />
                    <div className="flex items-center justify-between text-xs tabular-nums text-slate-500">
                        <span>{formatTime(current)}</span>
                        <span>{max > 0 ? formatTime(max) : "—"}</span>
                    </div>
                    <div className="flex items-center justify-center gap-3">
                        <button
                            type="button"
                            onClick={() => seekBy(-10)}
                            className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                        >
                            <LuRotateCcw className="h-4 w-4" />
                            10s
                        </button>
                        <button
                            type="button"
                            onClick={toggle}
                            className="inline-flex h-12 w-12 items-center justify-center rounded-full bg-brand text-white hover:bg-brand-dark"
                            aria-label={playing ? "Pause" : "Play"}
                        >
                            {playing ? <LuPause className="h-5 w-5" /> : <LuPlay className="ml-0.5 h-5 w-5" />}
                        </button>
                        <button
                            type="button"
                            onClick={() => seekBy(10)}
                            className="inline-flex items-center gap-1.5 rounded-full border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                        >
                            10s
                            <LuRotateCw className="h-4 w-4" />
                        </button>
                    </div>
                    <p className="text-center text-xs text-slate-400">
                        Drag the bar or use ← → to skip. Space plays or pauses.
                    </p>
                </div>
            )}
        </ReportModal>
    );
}

export function AudioPlayer({
    jobId,
    fileName,
}: Readonly<{ jobId?: string; fileName?: string }>) {
    const [open, setOpen] = useState(false);

    if (!jobId) {
        return <span className="text-slate-400">—</span>;
    }

    return (
        <>
            <button
                type="button"
                onClick={() => setOpen(true)}
                className="inline-flex items-center gap-1.5 rounded-full bg-brand-subtle px-2.5 py-1 text-xs font-semibold text-brand hover:bg-brand hover:text-white"
            >
                <LuPlay className="h-3.5 w-3.5" />
                Play
            </button>
            {open ? (
                <AudioPlaybackModal jobId={jobId} fileName={fileName} onClose={() => setOpen(false)} />
            ) : null}
        </>
    );
}
