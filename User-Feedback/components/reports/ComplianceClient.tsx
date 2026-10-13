"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { FiDownload, FiFilter } from "react-icons/fi";

import { Button } from "@/components/ui/button";
import { Pagination } from "@/components/ui/Pagination";
import { Select } from "@/components/ui/Select";
import { useCompliance, useReportFilterOptions } from "@/lib/hooks/reports";
import {
    datesForPeriod,
    defaultPeriod,
    filtersFromSearchParams,
    type PeriodKind,
    type PeriodState,
} from "@/lib/reports/period";
import type { ComplianceRow, FilterOptions, ReportFilters } from "@/lib/reports/types";

const PERIOD_TABS: { id: PeriodKind; label: string }[] = [
    { id: "month", label: "Monthly" },
    { id: "quarter", label: "Quarterly" },
    { id: "year", label: "Year" },
];

const QUARTER_OPTIONS = [
    { label: "Q1 (Jan–Mar)", value: "1" },
    { label: "Q2 (Apr–Jun)", value: "2" },
    { label: "Q3 (Jul–Sep)", value: "3" },
    { label: "Q4 (Oct–Dec)", value: "4" },
];

const EMPTY_FILTERS: FilterOptions = {
    divisions: [],
    zones: [],
    clusters: [],
    rfmm_clusters: [],
    states: [],
    products: [],
    data_sources: [],
    fme_codes: [],
    user_types: [],
};

function withAll(values: string[]): { label: string; value: string }[] {
    return [{ label: "All", value: "ALL" }, ...values.map((value) => ({ label: value, value }))];
}

function OptionalSelect({
    label,
    value,
    onChange,
    options,
}: {
    label: string;
    value?: string;
    onChange: (value: string) => void;
    options: string[];
}) {
    if (!options.length) return null;
    return (
        <div className="text-[12px] font-bold uppercase tracking-wider text-slate-600">
            {label}
            <Select
                className="mt-1"
                value={value || "ALL"}
                onChange={onChange}
                options={withAll(options)}
            />
        </div>
    );
}

function applySelect(prev: ReportFilters, key: keyof ReportFilters, value: string): ReportFilters {
    const next = { ...prev };
    if (!value || value === "ALL") delete next[key];
    else (next as Record<string, unknown>)[key] = value;
    return next;
}

function applyLinkedSelect(prev: ReportFilters, key: keyof ReportFilters, value: string): ReportFilters {
    const next = applySelect(prev, key, value);
    if (key === "division") {
        delete next.zone;
        delete next.cluster;
        delete next.fme_code;
    } else if (key === "zone") {
        delete next.cluster;
        delete next.fme_code;
    } else if (key === "cluster") {
        delete next.fme_code;
    }
    return next;
}

function sanitizeFilters(draft: ReportFilters, dates: Pick<ReportFilters, "start_date" | "end_date">): ReportFilters {
    const next: ReportFilters = { ...draft, ...dates };
    (Object.keys(next) as (keyof ReportFilters)[]).forEach((key) => {
        const value = next[key];
        if (value === undefined || value === null || value === "" || value === "ALL") {
            delete next[key];
        }
    });
    return next;
}

function formatDuration(seconds: number | null): string {
    if (seconds == null || Number.isNaN(seconds)) return "—";
    const total = Math.max(0, Math.round(seconds));
    const minutes = Math.floor(total / 60);
    const rest = total % 60;
    return `${minutes}:${String(rest).padStart(2, "0")}`;
}

const PAGE_SIZE_OPTIONS = [10, 20, 50];

function totalsFromRows(rows: ComplianceRow[]): ComplianceRow {
    const sitesVisited = rows.reduce((sum, row) => sum + (row.sites_visited || 0), 0);
    const sitesRecorded = rows.reduce((sum, row) => sum + (row.sites_recorded || 0), 0);
    let weighted = 0;
    let weight = 0;
    for (const row of rows) {
        if (row.avg_conversation_seconds == null || !row.sites_recorded) continue;
        weighted += row.avg_conversation_seconds * row.sites_recorded;
        weight += row.sites_recorded;
    }
    return {
        division: "Total",
        time_period: "",
        zone: "",
        user_type: "",
        rfmm_cluster: "",
        fme_code: "",
        fme_period: "",
        fme_name: "",
        sites_visited: sitesVisited,
        sites_recorded: sitesRecorded,
        conversation_rate: sitesVisited ? Math.round((sitesRecorded / sitesVisited) * 1000) / 10 : 0,
        avg_conversation_seconds: weight ? Math.round((weighted / weight) * 10) / 10 : null,
    };
}

function exportCsv(rows: ComplianceRow[]) {
    const headers = [
        "Division",
        "Time period",
        "Zone",
        "User type",
        "RFMM Cluster",
        "FME Code",
        "FME Period",
        "FME NAME",
        "Number of sites visited",
        "Number of sites visited, in which conversations were recorded",
        "% of visited sites where conversation recorded",
        "Average time of conversation recorded per visited site",
    ];
    const lineFor = (row: ComplianceRow) =>
        [
            row.division,
            row.time_period,
            row.zone,
            row.user_type,
            row.rfmm_cluster,
            row.fme_code,
            row.fme_period,
            row.fme_name,
            row.sites_visited,
            row.sites_recorded,
            `${row.conversation_rate}%`,
            formatDuration(row.avg_conversation_seconds),
        ]
            .map((value) => `"${String(value).replaceAll('"', '""')}"`)
            .join(",");
    const lines = [headers.join(","), ...rows.map(lineFor)];
    if (rows.length) lines.push(lineFor(totalsFromRows(rows)));
    const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "open-conversations-compliance.csv";
    link.click();
    URL.revokeObjectURL(url);
}

const COLUMNS: { key: keyof ComplianceRow; label: string; metric?: boolean; render?: (row: ComplianceRow) => string }[] = [
    { key: "division", label: "Division" },
    { key: "time_period", label: "Time period" },
    { key: "zone", label: "Zone" },
    { key: "user_type", label: "User type" },
    { key: "rfmm_cluster", label: "RFMM Cluster" },
    { key: "fme_code", label: "FME Code" },
    { key: "fme_period", label: "FME Period" },
    { key: "fme_name", label: "FME NAME" },
    { key: "sites_visited", label: "Number of sites visited", metric: true },
    {
        key: "sites_recorded",
        label: "Number of sites visited, in which conversations were recorded",
        metric: true,
    },
    {
        key: "conversation_rate",
        label: "% of visited sites where conversation recorded",
        metric: true,
        render: (row) => `${row.conversation_rate}%`,
    },
    {
        key: "avg_conversation_seconds",
        label: "Average time of conversation recorded per visited site",
        metric: true,
        render: (row) => formatDuration(row.avg_conversation_seconds),
    },
];

export default function ComplianceClient() {
    const searchParams = useSearchParams();
    const fromUrl = useMemo(() => filtersFromSearchParams(searchParams), [searchParams]);
    const initialPeriod = useMemo(
        () => defaultPeriod("month"),
        [],
    );
    const initialFilters = useMemo(() => {
        const dates = fromUrl.start_date && fromUrl.end_date
            ? { start_date: fromUrl.start_date, end_date: fromUrl.end_date }
            : datesForPeriod(initialPeriod);
        return { ...fromUrl, ...dates };
    }, [fromUrl, initialPeriod]);
    const [draft, setDraft] = useState<ReportFilters>(initialFilters);
    const [filters, setFilters] = useState<ReportFilters>(initialFilters);
    const [period, setPeriod] = useState<PeriodState>(
        fromUrl.start_date && fromUrl.end_date
            ? { kind: "month", month: fromUrl.start_date.slice(0, 7) }
            : initialPeriod,
    );
    const [showFilters, setShowFilters] = useState(true);
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(10);

    const filterQuery = useReportFilterOptions({
        division: draft.division,
        zone: draft.zone,
        cluster: draft.cluster,
    });
    const reportQuery = useCompliance(filters);
    const rows = reportQuery.data?.data?.items || [];
    // Prefer /filter-options; if that master list is empty, derive dropdowns from
    // the loaded compliance rows so Division/Zone/RFMM/BDE still appear.
    const rowFilterOptions = useMemo(() => {
        const uniq = (values: Array<string | null | undefined>) =>
            Array.from(
                new Set(values.map((value) => (value || "").trim()).filter(Boolean)),
            ).sort((a, b) => a.localeCompare(b));
        return {
            divisions: uniq(rows.map((row) => row.division)),
            zones: uniq(rows.map((row) => row.zone)),
            clusters: uniq(rows.map((row) => row.rfmm_cluster)),
            rfmm_clusters: uniq(rows.map((row) => row.rfmm_cluster)),
            fme_codes: uniq(rows.map((row) => row.fme_code)),
            user_types: uniq(rows.map((row) => row.user_type)),
        } satisfies Partial<FilterOptions>;
    }, [rows]);
    const linked = filterQuery.data?.data;
    const pick = (key: keyof FilterOptions) =>
        (linked?.[key]?.length ? linked[key] : rowFilterOptions[key as keyof typeof rowFilterOptions]) || [];
    const filterOptions: FilterOptions = {
        ...EMPTY_FILTERS,
        divisions: pick("divisions"),
        zones: pick("zones"),
        clusters: pick("clusters"),
        rfmm_clusters: pick("rfmm_clusters"),
        fme_codes: pick("fme_codes"),
        user_types: pick("user_types"),
        states: linked?.states || [],
        products: linked?.products || [],
        data_sources: linked?.data_sources || [],
    };
    const totals = useMemo(() => totalsFromRows(rows), [rows]);
    const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
    const currentPage = Math.min(page, totalPages);
    const pageRows = rows.slice((currentPage - 1) * pageSize, currentPage * pageSize);
    const showingFrom = rows.length ? (currentPage - 1) * pageSize + 1 : 0;
    const showingTo = Math.min(currentPage * pageSize, rows.length);
    const rfmmOptions = filterOptions.rfmm_clusters?.length ? filterOptions.rfmm_clusters : filterOptions.clusters;

    const applyFilters = () => {
        setPage(1);
        setFilters(sanitizeFilters(draft, datesForPeriod(period)));
    };
    const clearFilters = () => {
        const next = defaultPeriod("month");
        setDraft({});
        setPeriod(next);
        setFilters(datesForPeriod(next));
        setPage(1);
    };
    const selectPeriod = (kind: PeriodKind) => {
        const next = defaultPeriod(kind);
        setPeriod(next);
        setDraft((prev) => ({ ...prev, ...datesForPeriod(next) }));
    };
    const updatePeriod = (patch: Partial<PeriodState>) => {
        const next = { ...period, ...patch };
        setPeriod(next);
        setDraft((prev) => ({ ...prev, ...datesForPeriod(next) }));
    };

    return (
        <div className="p-6">
            <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                <div>
                    <Link href="/" className="text-xs font-medium text-brand hover:underline">
                        ← Back to home
                    </Link>
                    <h1 className="mt-1 text-2xl font-bold text-slate-900">Open Conversations</h1>
                    <p className="mt-1 text-sm text-slate-500">
                        Compliance by FME: sites visited versus sites where a conversation was recorded.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <Button variant="secondary" onClick={() => setShowFilters((value) => !value)}>
                        <FiFilter className="mr-2 h-4 w-4" />
                        {showFilters ? "Hide filters" : "Show filters"}
                    </Button>
                    <Button variant="secondary" onClick={() => exportCsv(rows)} disabled={!rows.length}>
                        <FiDownload className="mr-2 h-4 w-4" />
                        Export CSV
                    </Button>
                </div>
            </div>

            {showFilters ? (
                <div className="mb-5 grid grid-cols-1 gap-3 rounded-lg border border-slate-200 bg-white p-4 sm:grid-cols-2 xl:grid-cols-4">
                    <OptionalSelect
                        label="Division"
                        value={draft.division}
                        onChange={(value) => setDraft((prev) => applyLinkedSelect(prev, "division", value))}
                        options={filterOptions.divisions}
                    />
                    <OptionalSelect
                        label="Zone"
                        value={draft.zone}
                        onChange={(value) => setDraft((prev) => applyLinkedSelect(prev, "zone", value))}
                        options={filterOptions.zones}
                    />
                    <OptionalSelect
                        label="RFMM Cluster"
                        value={draft.cluster}
                        onChange={(value) => setDraft((prev) => applyLinkedSelect(prev, "cluster", value))}
                        options={rfmmOptions}
                    />
                    <OptionalSelect
                        label="FME / BDE"
                        value={draft.fme_code}
                        onChange={(value) => setDraft((prev) => applySelect(prev, "fme_code", value))}
                        options={filterOptions.fme_codes}
                    />
                    <OptionalSelect
                        label="User type"
                        value={draft.user_type}
                        onChange={(value) => setDraft((prev) => applySelect(prev, "user_type", value))}
                        options={filterOptions.user_types}
                    />
                    <label className="text-[12px] font-bold uppercase tracking-wider text-slate-600">
                        Time period
                        <Select
                            className="mt-1"
                            value={period.kind}
                            onChange={(value) => selectPeriod(value as PeriodKind)}
                            options={PERIOD_TABS.map((tab) => ({ label: tab.label, value: tab.id }))}
                        />
                    </label>
                    {period.kind === "month" ? (
                        <label className="text-[12px] font-bold uppercase tracking-wider text-slate-600">
                            Month
                            <input
                                type="month"
                                value={period.month || ""}
                                onChange={(event) => updatePeriod({ month: event.target.value })}
                                className="mt-1 h-9 w-full rounded border border-border bg-surface px-3 text-sm"
                            />
                        </label>
                    ) : null}
                    {period.kind === "quarter" || period.kind === "year" ? (
                        <label className="text-[12px] font-bold uppercase tracking-wider text-slate-600">
                            Year
                            <input
                                type="number"
                                min="2000"
                                max="2100"
                                value={period.year || ""}
                                onChange={(event) => updatePeriod({ year: event.target.value })}
                                className="mt-1 h-9 w-full rounded border border-border bg-surface px-3 text-sm"
                            />
                        </label>
                    ) : null}
                    {period.kind === "quarter" ? (
                        <label className="text-[12px] font-bold uppercase tracking-wider text-slate-600">
                            Quarter
                            <Select
                                className="mt-1"
                                value={period.quarter || ""}
                                onChange={(value) => updatePeriod({ quarter: value })}
                                options={QUARTER_OPTIONS}
                            />
                        </label>
                    ) : null}
                    <div className="flex items-end gap-2">
                        <Button type="button" onClick={applyFilters}>
                            Apply
                        </Button>
                        <Button type="button" variant="secondary" onClick={clearFilters}>
                            Clear
                        </Button>
                    </div>
                </div>
            ) : null}

            <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
                <table className="min-w-full border-collapse text-left text-sm">
                    <thead>
                        <tr className="border-b border-slate-200 bg-slate-50">
                            {COLUMNS.map((column) => (
                                <th
                                    key={column.key}
                                    className={`whitespace-normal px-3 py-3 text-[13px] font-semibold uppercase tracking-wide text-slate-600 ${
                                        column.metric ? "text-slate-900" : ""
                                    }`}
                                >
                                    {column.label}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {reportQuery.isLoading && !rows.length ? (
                            <tr>
                                <td colSpan={COLUMNS.length} className="px-3 py-6 text-sm text-slate-500">
                                    Loading compliance…
                                </td>
                            </tr>
                        ) : rows.length === 0 ? (
                            <tr>
                                <td colSpan={COLUMNS.length} className="px-3 py-6 text-sm text-slate-500">
                                    No site visits in this period.
                                </td>
                            </tr>
                        ) : (
                            <>
                                {pageRows.map((row) => (
                                    <tr
                                        key={`${row.division}-${row.zone}-${row.fme_code}-${row.user_type}-${row.rfmm_cluster}`}
                                        className="border-b border-slate-100"
                                    >
                                        {COLUMNS.map((column) => (
                                            <td
                                                key={column.key}
                                                className={`whitespace-nowrap px-3 py-2.5 ${
                                                    column.metric ? "font-semibold text-slate-900" : "text-slate-700"
                                                }`}
                                            >
                                                {column.render ? column.render(row) : String(row[column.key] ?? "")}
                                            </td>
                                        ))}
                                    </tr>
                                ))}
                                <tr className="border-t-2 border-slate-300 bg-slate-50">
                                    {COLUMNS.map((column, index) => (
                                        <td
                                            key={column.key}
                                            className="whitespace-nowrap px-3 py-3 font-semibold text-slate-900"
                                        >
                                            {index === 0
                                                ? "Total"
                                                : column.metric
                                                  ? column.render
                                                      ? column.render(totals)
                                                      : String(totals[column.key] ?? "")
                                                  : ""}
                                        </td>
                                    ))}
                                </tr>
                            </>
                        )}
                    </tbody>
                </table>
                {rows.length ? (
                    <Pagination
                        currentPage={currentPage}
                        totalPages={totalPages}
                        pageSize={pageSize}
                        pageSizeOptions={PAGE_SIZE_OPTIONS}
                        totalItems={rows.length}
                        showingFrom={showingFrom}
                        showingTo={showingTo}
                        itemLabel="FMEs"
                        selectId="compliance-page-size"
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
