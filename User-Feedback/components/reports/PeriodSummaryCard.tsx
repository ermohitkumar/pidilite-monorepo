import { FormattedSummary } from "@/components/reports/FormattedSummary";
import { hasVisibleSummary } from "@/lib/reports/period";
import type { PeriodSummaryRecord } from "@/lib/reports/types";

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

export function PeriodSummaryCard({
    title,
    record,
    emptyLabel,
    hideMeta = false,
}: {
    title: string;
    record?: PeriodSummaryRecord | null;
    emptyLabel: string;
    hideMeta?: boolean;
}) {
    if (!record || (!hasVisibleSummary(record) && record.status !== "error")) {
        return (
            <section className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-slate-700">
                <h3 className="text-base font-semibold text-slate-800">{title}</h3>
                <p className="mt-2 text-base text-slate-500">{emptyLabel}</p>
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
                    />
                </div>
            )}
            <div className="mt-3 flex flex-wrap items-center gap-3 text-sm text-slate-500">
                <span title="Distinct field calls / site visits that contributed to this summary">
                    {Number(highlights.site_visit_count ?? record.call_count ?? 0)} site visits
                </span>
                <span title="Tagged feedback rows used as input; the text above is an AI-condensed theme, not one bullet per insight">
                    {record.insight_count ?? 0} insights summarized
                </span>
                {highlights.truncated ? <span>Sampled for length</span> : null}
            </div>
        </section>
    );
}
