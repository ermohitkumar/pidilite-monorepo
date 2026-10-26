import Link from "next/link";

import { FormattedSummary } from "@/components/reports/FormattedSummary";
import { hasVisibleSummary } from "@/lib/reports/period";
import type { PeriodSummaryRecord, ReportThemeCount } from "@/lib/reports/types";

export const PERIOD_GRAIN_LABEL: Record<string, string> = {
    bde: "BDE",
    rfmm: "RFMM cluster",
    zone: "Zone",
    division: "Division",
    product: "Product",
    tag: "Tag",
    bde_pt: "BDE × product × tag",
    rfmm_pt: "RFMM × product × tag",
    zone_pt: "Zone × product × tag",
    div_pt: "Division × product × tag",
    bde_p: "BDE × product",
    rfmm_p: "RFMM × product",
    zone_p: "Zone × product",
    div_p: "Division × product",
    bde_t: "BDE × tag",
    rfmm_t: "RFMM × tag",
    zone_t: "Zone × tag",
    div_t: "Division × tag",
};

function statusClass(status?: string) {
    if (status === "error") return "border-amber-300 bg-amber-50 text-amber-950";
    return "border-slate-200 bg-white text-slate-800";
}

function sameName(left?: string | null, right?: string | null): boolean {
    return (left || "").replace(/\s+/g, " ").trim().toLowerCase() === (right || "").replace(/\s+/g, " ").trim().toLowerCase();
}

function sentenceCase(value: string): string {
    const text = value.trim();
    if (!text) return "";
    return text[0].toUpperCase() + text.slice(1);
}

function isShortTheme(theme: string, title: string): boolean {
    const text = theme.replace(/\s+/g, " ").trim();
    if (!text || sameName(text, title)) return false;
    if (/[.!?]/.test(text)) return false;
    return text.split(" ").length <= 6 && text.length <= 48;
}

type ThemeCountItem = { label: string; count: number };

function isOthersTheme(value: string): boolean {
    return value.replace(/\s+/g, " ").trim().toLowerCase() === "others";
}

function sortThemeCounts(items: ThemeCountItem[]): ThemeCountItem[] {
    return [...items].sort((left, right) => {
        const others = Number(isOthersTheme(left.label)) - Number(isOthersTheme(right.label));
        if (others) return others;
        return right.count - left.count || left.label.localeCompare(right.label);
    });
}

function themeCountItems(
    themes: ReportThemeCount[] | undefined,
    highlights: PeriodSummaryRecord["highlights"] | undefined,
    title: string,
): ThemeCountItem[] {
    const fromFindings = new Map<string, ThemeCountItem>();
    for (const finding of highlights?.findings || []) {
        for (const point of finding.points || []) {
            const theme = String(point.theme || "").trim();
            if (!isShortTheme(theme, title)) continue;
            const count = Number(point.user_count || 0);
            if (count < 1) continue;
            const key = theme.toLowerCase();
            const prev = fromFindings.get(key);
            if (prev) prev.count += count;
            else fromFindings.set(key, { label: sentenceCase(theme), count });
        }
    }
    if (fromFindings.size) return sortThemeCounts([...fromFindings.values()]);
    return sortThemeCounts(
        (themes || [])
            .filter((item) => item.theme && isShortTheme(item.theme, title) && Number(item.feedback_count) > 0)
            .map((item) => ({ label: sentenceCase(item.theme), count: Number(item.feedback_count) })),
    );
}

function ThemeCounts({ items }: { items: ThemeCountItem[] }) {
    if (!items.length) return null;
    return (
        <p className="mt-3 text-sm text-slate-800">
            {items.map((item, index) => (
                <span key={item.label}>
                    {index > 0 ? ", " : null}
                    <span className="font-semibold">{item.count} {item.label}</span>
                </span>
            ))}
        </p>
    );
}

export function PeriodSummaryCard({
    title,
    record,
    emptyLabel,
    hideMeta = false,
    insightsHref,
    productHref,
    themes,
}: {
    title: string;
    record?: PeriodSummaryRecord | null;
    emptyLabel: string;
    hideMeta?: boolean;
    insightsHref?: string;
    productHref?: (product: string) => string;
    themes?: ReportThemeCount[];
}) {
    const counts = themeCountItems(themes, record?.highlights, title);
    if (!record || (!hasVisibleSummary(record) && record.status !== "error")) {
        return (
            <section className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-slate-700">
                <h3 className="text-base font-semibold text-slate-800">{title}</h3>
                <p className="mt-2 text-base text-slate-500">{emptyLabel}</p>
                <ThemeCounts items={counts} />
                {insightsHref ? (
                    <Link href={insightsHref} className="mt-3 inline-block text-sm font-medium text-brand hover:underline">
                        View feedback
                    </Link>
                ) : null}
            </section>
        );
    }
    const highlights = record.highlights || {};
    return (
        <section className={`rounded-lg border p-4 ${statusClass(record.status)}`}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-base font-semibold">{title}</h3>
                {hideMeta ? null : (
                    <p className="text-sm text-slate-500">
                        {PERIOD_GRAIN_LABEL[record.grain] || record.grain} · {record.period_key}
                    </p>
                )}
            </div>
            {record.status === "error" ? (
                <p className="mt-2 text-base">{record.error_message || "This summary could not be generated."}</p>
            ) : (
                <div className="mt-3">
                    <FormattedSummary
                        text={record.summary_text}
                        highlights={highlights}
                        heading={title}
                        emptyLabel={emptyLabel}
                        productHref={productHref}
                    />
                </div>
            )}
            <ThemeCounts items={counts} />
            <div className="mt-3 flex flex-wrap items-center gap-3 text-sm text-slate-500">
                <span title="Distinct field calls / site visits that contributed to this summary">
                    {Number(highlights.site_visit_count ?? record.call_count ?? 0)} site visits
                </span>
                <span title="Tagged feedback rows used as input; the text above is an AI-condensed theme, not one bullet per feedback row">
                    {record.insight_count ?? 0} feedback
                </span>
                {insightsHref ? (
                    <Link href={insightsHref} className="font-medium text-brand hover:underline">
                        View feedback
                    </Link>
                ) : null}
                {highlights.truncated ? <span>Sampled for length</span> : null}
            </div>
        </section>
    );
}
