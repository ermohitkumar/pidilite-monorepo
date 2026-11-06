/** Human-readable job/pipeline error for failed-file tables and detail views. */
export function formatPipelineError(message: string | null | undefined): string {
    if (!message) return "";
    let text = message.trim();
    text = text.replace(/^\[pipeline:[^\]]+\]\s*/i, "");
    text = text.replace(/^\[STTInvalidArgumentError\]\s*/i, "");
    text = text.replace(/^\[STTGeminiTransientError\]\s*/i, "");
    text = text.replace(/^\[Unexpected\]\s*/i, "");

    const lower = text.toLowerCase();

    // Duration gate (current + legacy copy). Check before word-count rewrite —
    // short-audio messages may also mention spoken words.
    if (lower.includes("recording too short") || lower.includes("audio too short")) {
        const match = lower.match(
            /(?:recording|audio) too short:\s*(\d+)s\s*\(need at least\s*(\d+)s\)/,
        );
        if (match) {
            return (
                `Recording too short — ${match[1]}s (need at least ${match[2]}s). ` +
                "File marked failed."
            );
        }
        return "Recording too short (under the minimum duration). File marked failed.";
    }

    if (lower.includes("too few words") || /got\s+\d+\s+word/.test(lower)) {
        return (
            "Recording has too few spoken words — at least 100 words are required. " +
            "File marked failed (empty, silent, or unintelligible audio)."
        );
    }
    return text;
}
