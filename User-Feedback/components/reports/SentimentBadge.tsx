import { normalizeSentiment, type SentimentLabel } from "@/lib/reports/sentiment";

const SENTIMENT_CLASS: Record<SentimentLabel, string> = {
    Positive: "border-emerald-200 bg-emerald-50 text-emerald-800",
    Neutral: "border-slate-200 bg-slate-50 text-slate-700",
    Negative: "border-rose-200 bg-rose-50 text-rose-800",
};

export function SentimentBadge({
    value,
    size = "sm",
}: {
    value?: string | null;
    size?: "sm" | "md";
}) {
    const label = normalizeSentiment(value);
    if (!label) return <span className="text-[15px] text-slate-400">—</span>;
    const sizing = size === "md" ? "px-2.5 py-1 text-sm" : "px-2 py-0.5 text-[15px]";
    return (
        <span className={`inline-flex items-center rounded-full border font-medium ${sizing} ${SENTIMENT_CLASS[label]}`}>
            {label}
        </span>
    );
}
