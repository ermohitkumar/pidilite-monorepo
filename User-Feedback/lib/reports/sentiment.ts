export type SentimentLabel = "Positive" | "Neutral" | "Negative";

export type SummaryTopic = {
    label: string;
    user_count: number;
};

export function normalizeSentiment(value?: string | null): SentimentLabel | null {
    const raw = (value || "").trim().toLowerCase();
    if (raw === "positive" || raw === "pos") return "Positive";
    if (raw === "negative" || raw === "neg") return "Negative";
    if (raw === "neutral" || raw === "neu") return "Neutral";
    return null;
}

export function majoritySentiment(values: Array<string | null | undefined>): SentimentLabel | null {
    const counts: Record<SentimentLabel, number> = { Positive: 0, Neutral: 0, Negative: 0 };
    for (const value of values) {
        const label = normalizeSentiment(value);
        if (label) counts[label] += 1;
    }
    const ranked = (Object.entries(counts) as Array<[SentimentLabel, number]>).sort((a, b) => b[1] - a[1]);
    return ranked[0][1] > 0 ? ranked[0][0] : null;
}

export function topicUserLabel(count: number): string {
    return `${count} user${count === 1 ? "" : "s"}`;
}

export function topicReportedSentence(count: number, label: string): string {
    const clean = label.trim().replace(/\.+$/, "");
    const text = clean ? clean[0].toUpperCase() + clean.slice(1) : clean;
    const noun = count === 1 ? "user" : "users";
    return `${text} (${count} ${noun}).`;
}

export function similarObservationLabel(count: number): string {
    if (count < 1) return "";
    if (count === 1) return "(1 user)";
    return `(${count} users)`;
}
