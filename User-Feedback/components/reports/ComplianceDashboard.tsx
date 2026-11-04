"use client";

import { useMemo, useState } from "react";
import {
    Bar,
    BarChart,
    CartesianGrid,
    Cell,
    LabelList,
    Legend,
    ResponsiveContainer,
    Tooltip,
    XAxis,
    YAxis,
} from "recharts";

import { Button } from "@/components/ui/button";
import { Pagination } from "@/components/ui/Pagination";
import { Select } from "@/components/ui/Select";
import { useCompliancePipeline } from "@/lib/hooks/reports";
import {
    datesForPipelinePeriod,
    defaultPipelinePeriod,
    grainForPipelinePeriod,
    type PipelinePeriodKind,
    type PipelinePeriodState,
} from "@/lib/reports/period";
import type { PipelineDurationBucket, PipelineFailedReason, PipelineSiteRow } from "@/lib/reports/types";

const PERIOD_OPTIONS: { label: string; value: PipelinePeriodKind }[] = [
    { label: "Weekly", value: "week" },
    { label: "Monthly", value: "month" },
    { label: "Yearly", value: "year" },
];

const COLORS = {
    processed: "#2563eb",
    successful: "#16a34a",
    failed: "#dc2626",
    bucket: "#6366f1",
};

const REASON_META: Record<PipelineFailedReason["reason"], { label: string; color: string }> = {
    no_insights: { label: "No insights", color: "#f59e0b" },
    few_words: { label: "Too few words", color: "#a855f7" },
    short_audio: { label: "Audio under 120s", color: "#0ea5e9" },
    errors: { label: "Errors", color: "#dc2626" },
};

const BUCKET_LABELS: Record<string, string> = {
    "0-5": "0–5 min",
    "5-10": "5–10 min",
    "10-15": "10–15 min",
    "15-20": "15–20 min",
    "20+": "Above 20 min",
    unknown: "Unknown",
};

const TOP_SITES = 15;
const PAGE_SIZE_OPTIONS = [10, 20, 50];
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function percent(part: number, whole: number): string {
    return whole ? `${Math.round((part / whole) * 1000) / 10}%` : "—";
}

function seriesLabel(key: string): string {
    const month = /^(\d{4})-(\d{2})$/.exec(key);
    if (month) return MONTHS[Number(month[2]) - 1] || key;
    const day = /^\d{4}-(\d{2})-(\d{2})$/.exec(key);
    if (day) return `${day[2]} ${MONTHS[Number(day[1]) - 1] || ""}`.trim();
    return key;
}

/** Weighted average minutes across buckets that know their duration. */
function avgMinutes(buckets: PipelineDurationBucket[]): number | null {
    let total = 0;
    let count = 0;
    for (const bucket of buckets) {
        if (bucket.avg_minutes == null || !bucket.count) continue;
        total += bucket.avg_minutes * bucket.count;
        count += bucket.count;
    }
    return count ? Math.round((total / count) * 10) / 10 : null;
}

function reasonCount(row: PipelineSiteRow, reason: PipelineFailedReason["reason"]): number {
    return row.failed_reasons.find((item) => item.reason === reason)?.count ?? 0;
}

function StatCard({ label, value, hint, tone }: { label: string; value: number; hint?: string; tone: string }) {
    return (
        <div className="rounded-lg border border-slate-200 bg-white p-4">
            <p className="text-[12px] font-bold uppercase tracking-wider text-slate-500">{label}</p>
            <p className="mt-1 text-3xl font-bold" style={{ color: tone }}>
                {value.toLocaleString()}
            </p>
            {hint ? <p className="mt-1 text-xs text-slate-500">{hint}</p> : null}
        </div>
    );
}

function ChartCard({
    title,
    subtitle,
    children,
    className = "",
}: {
    title: string;
    subtitle?: string;
    children: React.ReactNode;
    className?: string;
}) {
    return (
        <div className={`rounded-lg border border-slate-200 bg-white p-4 ${className}`}>
            <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
            {subtitle ? <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p> : null}
            <div className="mt-3 h-72">{children}</div>
        </div>
    );
}

function BucketTooltip({
    active,
    payload,
}: {
    active?: boolean;
    payload?: { payload: PipelineDurationBucket & { label: string } }[];
}) {
    if (!active || !payload?.length) return null;
    const row = payload[0].payload;
    return (
        <div className="rounded border border-slate-200 bg-white px-3 py-2 text-xs shadow">
            <p className="font-semibold text-slate-900">{row.label}</p>
            <p className="text-slate-600">Files: {row.count.toLocaleString()}</p>
            <p className="text-slate-600">
                Avg duration: {row.avg_minutes == null ? "—" : `${row.avg_minutes} min`}
            </p>
        </div>
    );
}

export default function ComplianceDashboard() {
    const [period, setPeriod] = useState<PipelinePeriodState>(() => defaultPipelinePeriod("month"));
    const [draftSite, setDraftSite] = useState("ALL");
    const [site, setSite] = useState("ALL");
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(10);

    const userTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    const query = useCompliancePipeline({
        ...datesForPipelinePeriod(period),
        grain: grainForPipelinePeriod(period.kind),
        site_number: site === "ALL" ? undefined : site,
        user_timezone: userTimezone,
    });
    const data = query.data?.data;
    const totals = data?.totals ?? { processed: 0, successful: 0, failed: 0 };

    const series = useMemo(
        () => (data?.series ?? []).map((point) => ({ ...point, label: seriesLabel(point.key) })),
        [data],
    );
    const buckets = useMemo(
        () =>
            (data?.duration_buckets ?? []).map((bucket) => ({
                ...bucket,
                label: BUCKET_LABELS[bucket.bucket] ?? bucket.bucket,
            })),
        [data],
    );
    const reasons = useMemo(
        () =>
            (data?.failed_reasons ?? []).map((item) => ({
                ...item,
                label: REASON_META[item.reason]?.label ?? item.reason,
                color: REASON_META[item.reason]?.color ?? COLORS.failed,
            })),
        [data],
    );
    const sites = useMemo(() => data?.by_site ?? [], [data]);
    const topSites = useMemo(() => sites.slice(0, TOP_SITES), [sites]);
    const overallAvg = useMemo(() => avgMinutes(data?.duration_buckets ?? []), [data]);

    const totalPages = Math.max(1, Math.ceil(sites.length / pageSize));
    const currentPage = Math.min(page, totalPages);
    const pageRows = sites.slice((currentPage - 1) * pageSize, currentPage * pageSize);

    const selectKind = (kind: PipelinePeriodKind) => {
        setPeriod(defaultPipelinePeriod(kind));
        setPage(1);
    };
    const updatePeriod = (patch: Partial<PipelinePeriodState>) => {
        setPeriod((prev) => ({ ...prev, ...patch }));
        setPage(1);
    };
    const siteOptions = [
        { label: "All sites", value: "ALL" },
        ...(data?.sites ?? []).map((value) => ({ label: value, value })),
    ];

    return (
        <div>
            <div className="mb-4">
                <h2 className="text-xl font-bold text-slate-900">Dashboard</h2>
                <p className="mt-1 text-sm text-slate-500">
                    Files processed in the period: successful (at least one insight) versus failed (no insights,
                    too few words, audio under 120s or pipeline errors).
                </p>
            </div>

            <div className="mb-5 grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-2 xl:grid-cols-4">
                <label className="text-[12px] font-bold uppercase tracking-wider text-slate-600">
                    Frequency
                    <Select
                        className="mt-1"
                        value={period.kind}
                        onChange={(value) => selectKind(value as PipelinePeriodKind)}
                        options={PERIOD_OPTIONS}
                    />
                </label>
                {period.kind === "week" ? (
                    <label className="text-[12px] font-bold uppercase tracking-wider text-slate-600">
                        Week
                        <input
                            type="week"
                            value={period.week || ""}
                            onChange={(event) => event.target.value && updatePeriod({ week: event.target.value })}
                            className="mt-1 h-9 w-full rounded border border-border bg-surface px-3 text-sm"
                        />
                    </label>
                ) : null}
                {period.kind === "month" ? (
                    <label className="text-[12px] font-bold uppercase tracking-wider text-slate-600">
                        Month
                        <input
                            type="month"
                            value={period.month || ""}
                            onChange={(event) => event.target.value && updatePeriod({ month: event.target.value })}
                            className="mt-1 h-9 w-full rounded border border-border bg-surface px-3 text-sm"
                        />
                    </label>
                ) : null}
                {period.kind === "year" ? (
                    <label className="text-[12px] font-bold uppercase tracking-wider text-slate-600">
                        Year
                        <input
                            type="number"
                            min="2000"
                            max="2100"
                            value={period.year || ""}
                            onChange={(event) => event.target.value && updatePeriod({ year: event.target.value })}
                            className="mt-1 h-9 w-full rounded border border-border bg-surface px-3 text-sm"
                        />
                    </label>
                ) : null}
                <label className="text-[12px] font-bold uppercase tracking-wider text-slate-600">
                    Site
                    <Select className="mt-1" value={draftSite} onChange={setDraftSite} options={siteOptions} />
                </label>
                <div className="flex items-end gap-2">
                    <Button
                        type="button"
                        onClick={() => {
                            setSite(draftSite);
                            setPage(1);
                        }}
                    >
                        Apply
                    </Button>
                    <Button
                        type="button"
                        variant="secondary"
                        onClick={() => {
                            setDraftSite("ALL");
                            setSite("ALL");
                            setPeriod(defaultPipelinePeriod("month"));
                            setPage(1);
                        }}
                    >
                        Clear
                    </Button>
                </div>
            </div>

            {query.isError ? (
                <p className="mb-4 rounded border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                    Could not load the dashboard. Try again.
                </p>
            ) : null}
            {query.isLoading && !data ? <p className="mb-4 text-sm text-slate-500">Loading dashboard…</p> : null}

            <div className="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <StatCard label="Total files processed" value={totals.processed} tone={COLORS.processed} hint={data?.period} />
                <StatCard
                    label="Successful"
                    value={totals.successful}
                    tone={COLORS.successful}
                    hint={`${percent(totals.successful, totals.processed)} of processed · at least one insight`}
                />
                <StatCard
                    label="Failed"
                    value={totals.failed}
                    tone={COLORS.failed}
                    hint={`${percent(totals.failed, totals.processed)} of processed`}
                />
                <div className="rounded-lg border border-slate-200 bg-white p-4">
                    <p className="text-[12px] font-bold uppercase tracking-wider text-slate-500">Avg audio duration</p>
                    <p className="mt-1 text-3xl font-bold text-slate-900">
                        {overallAvg == null ? "—" : `${overallAvg} min`}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">Across files with a known duration</p>
                </div>
            </div>

            <div className="mb-5 grid grid-cols-1 gap-4 xl:grid-cols-2">
                <ChartCard
                    title="Files processed over time"
                    subtitle={period.kind === "year" ? "Monthly" : "Daily"}
                    className="xl:col-span-2"
                >
                    <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={series}>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} />
                            <XAxis dataKey="label" tick={{ fontSize: 11 }} interval="preserveStartEnd" />
                            <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                            <Tooltip />
                            <Legend />
                            <Bar dataKey="successful" name="Successful" stackId="files" fill={COLORS.successful} />
                            <Bar dataKey="failed" name="Failed" stackId="files" fill={COLORS.failed} />
                        </BarChart>
                    </ResponsiveContainer>
                </ChartCard>

                <ChartCard title="Audio duration buckets" subtitle="File count per bucket; label shows average minutes">
                    <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={buckets} margin={{ top: 20 }}>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} />
                            <XAxis dataKey="label" tick={{ fontSize: 11 }} />
                            <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                            <Tooltip content={<BucketTooltip />} />
                            <Bar dataKey="count" name="Files" fill={COLORS.bucket}>
                                <LabelList
                                    dataKey="avg_minutes"
                                    position="top"
                                    fontSize={11}
                                    formatter={(value: unknown) => (value == null ? "" : `avg ${value}m`)}
                                />
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                </ChartCard>

                <ChartCard
                    title="Failed files by reason"
                    subtitle={`${totals.failed.toLocaleString()} failed files`}
                >
                    <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={reasons} layout="vertical" margin={{ left: 20, right: 40 }}>
                            <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                            <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
                            <YAxis type="category" dataKey="label" width={110} tick={{ fontSize: 11 }} />
                            <Tooltip />
                            <Bar dataKey="count" name="Files">
                                {reasons.map((item) => (
                                    <Cell key={item.reason} fill={item.color} />
                                ))}
                                <LabelList dataKey="count" position="right" fontSize={11} />
                            </Bar>
                        </BarChart>
                    </ResponsiveContainer>
                </ChartCard>

                <ChartCard
                    title="Site-wise processing"
                    subtitle={`Top ${Math.min(TOP_SITES, sites.length)} sites by files processed`}
                    className="xl:col-span-2"
                >
                    <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={topSites}>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} />
                            <XAxis dataKey="site_number" tick={{ fontSize: 11 }} interval={0} angle={-30} textAnchor="end" height={60} />
                            <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                            <Tooltip />
                            <Legend />
                            <Bar dataKey="successful" name="Successful" stackId="site" fill={COLORS.successful} />
                            <Bar dataKey="failed" name="Failed" stackId="site" fill={COLORS.failed} />
                        </BarChart>
                    </ResponsiveContainer>
                </ChartCard>
            </div>

            <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
                <table className="min-w-full border-collapse text-left text-sm">
                    <thead>
                        <tr className="border-b border-slate-200 bg-slate-50 text-[13px] font-semibold uppercase tracking-wide text-slate-600">
                            <th className="px-3 py-3">Site</th>
                            <th className="px-3 py-3 text-right">Processed</th>
                            <th className="px-3 py-3 text-right">Successful</th>
                            <th className="px-3 py-3 text-right">Failed</th>
                            <th className="px-3 py-3 text-right">Success rate</th>
                            <th className="px-3 py-3 text-right">No insights</th>
                            <th className="px-3 py-3 text-right">Too few words</th>
                            <th className="px-3 py-3 text-right">Audio under 120s</th>
                            <th className="px-3 py-3 text-right">Errors</th>
                            <th className="px-3 py-3 text-right">Avg duration</th>
                        </tr>
                    </thead>
                    <tbody>
                        {sites.length === 0 ? (
                            <tr>
                                <td colSpan={10} className="px-3 py-6 text-sm text-slate-500">
                                    {query.isLoading ? "Loading sites…" : "No files processed in this period."}
                                </td>
                            </tr>
                        ) : (
                            pageRows.map((row) => {
                                const avg = avgMinutes(row.duration_buckets);
                                return (
                                    <tr key={row.site_number} className="border-b border-slate-100">
                                        <td className="whitespace-nowrap px-3 py-2.5 text-slate-700">{row.site_number}</td>
                                        <td className="px-3 py-2.5 text-right font-semibold text-slate-900">{row.processed}</td>
                                        <td className="px-3 py-2.5 text-right text-green-700">{row.successful}</td>
                                        <td className="px-3 py-2.5 text-right text-red-700">{row.failed}</td>
                                        <td className="px-3 py-2.5 text-right">{percent(row.successful, row.processed)}</td>
                                        <td className="px-3 py-2.5 text-right">{reasonCount(row, "no_insights")}</td>
                                        <td className="px-3 py-2.5 text-right">{reasonCount(row, "few_words")}</td>
                                        <td className="px-3 py-2.5 text-right">{reasonCount(row, "short_audio")}</td>
                                        <td className="px-3 py-2.5 text-right">{reasonCount(row, "errors")}</td>
                                        <td className="px-3 py-2.5 text-right">{avg == null ? "—" : `${avg} min`}</td>
                                    </tr>
                                );
                            })
                        )}
                    </tbody>
                </table>
                {sites.length ? (
                    <Pagination
                        currentPage={currentPage}
                        totalPages={totalPages}
                        pageSize={pageSize}
                        pageSizeOptions={PAGE_SIZE_OPTIONS}
                        totalItems={sites.length}
                        showingFrom={(currentPage - 1) * pageSize + 1}
                        showingTo={Math.min(currentPage * pageSize, sites.length)}
                        itemLabel="sites"
                        selectId="compliance-dashboard-page-size"
                        onPageChange={setPage}
                        onPageSizeChange={(size) => {
                            setPageSize(size);
                            setPage(1);
                        }}
                    />
                ) : null}
            </div>
        </div>
    );
}
