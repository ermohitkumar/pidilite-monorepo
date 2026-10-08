/** Human-readable job/pipeline error for failed-file tables and detail views. */
export function formatPipelineError(message: string | null | undefined): string {
    if (!message) return "";
    let text = message.trim();
    text = text.replace(/^\[pipeline:[^\]]+\]\s*/i, "");
    text = text.replace(/^\[STTInvalidArgumentError\]\s*/i, "");
    text = text.replace(/^\[STTGeminiTransientError\]\s*/i, "");
    text = text.replace(/^\[Unexpected\]\s*/i, "");

    const lower = text.toLowerCase();
    if (
        lower.includes("too few words") ||
        lower.includes("need at least") ||
        /got\s+\d+\s+word/.test(lower)
    ) {
        return (
            "Recording has too few spoken words — at least 100 words are required. " +
            "File marked failed (empty, silent, or unintelligible audio)."
        );
    }
    return text;
}
