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
}: {
    title: string;
    record?: PeriodSummaryRecord | null;
    emptyLabel: string;
}) {
    if (!record || (!hasVisibleSummary(record) && record.status !== "error")) {
        return (
            <section className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-slate-700">
                <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
                <p className="mt-2 text-sm text-slate-500">{emptyLabel}</p>
            </section>
        );
    }
    const highlights = record.highlights || {};
    return (
        <section className={`rounded-lg border p-4 ${statusClass(record.status)}`}>
            <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="text-sm font-semibold">{title}</h3>
                <p className="text-xs text-slate-500">
                    {PERIOD_GRAIN_LABEL[record.grain] || record.grain} · {record.grain_key} · {record.period_key}
                </p>
            </div>
            {record.status === "error" ? (
                <p className="mt-2 text-sm">{record.error_message || "This summary could not be generated."}</p>
            ) : (
                <div className="mt-3">
                    <FormattedSummary text={record.summary_text} highlights={highlights} emptyLabel={emptyLabel} />
                </div>
            )}
            <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
                <span>{record.call_count ?? 0} calls</span>
                <span>{record.insight_count ?? 0} insights</span>
                {highlights.truncated ? <span>Sampled for length</span> : null}
            </div>
        </section>
    );
}
