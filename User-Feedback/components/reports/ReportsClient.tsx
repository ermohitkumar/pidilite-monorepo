"use client";

import { useMemo, useState } from "react";
import { FiDownload, FiFilter } from "react-icons/fi";
import { LuLoader } from "react-icons/lu";

import { ConversationThread } from "@/components/reports/ConversationThread";
import { FileSourceLink } from "@/components/reports/FileSourceLink";
import { ReportDrillView } from "@/components/reports/ReportDrillView";
import { ReportModal } from "@/components/reports/ReportModal";
import { exportMatrixCsv, ReportTable } from "@/components/reports/ReportTable";
import { Button } from "@/components/ui/button";
import { SearchInput } from "@/components/ui/SearchInput";
import { Select } from "@/components/ui/Select";
import { useReportConversation, useReportFilterOptions, useReportSummary } from "@/lib/hooks/reports";
import { buildTagMatrixFromSummary, columnsForOverview } from "@/lib/reports/build";
import { isFullConversationTitle, parseConversationTurns } from "@/lib/reports/conversation";
import { datesForPeriod, defaultPeriod, type PeriodKind, type PeriodState } from "@/lib/reports/period";
import {
    COLUMN_LABELS,
    GROUP_TABS,
    type DrillScope,
    type FeedbackGroup,
    type FilterOptions,
    type MatrixColumn,
    type MatrixRow,
    type ReportFilters,
} from "@/lib/reports/types";

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

function sanitizeFilters(draft: ReportFilters, search: string, dates: Pick<ReportFilters, "start_date" | "end_date">): ReportFilters {
    const next: ReportFilters = { ...draft, ...dates };
    if (search.trim()) next.search = search.trim();
    else delete next.search;
    (Object.keys(next) as (keyof ReportFilters)[]).forEach((key) => {
        const value = next[key];
        if (value === undefined || value === null || value === "" || value === "ALL") {
            delete next[key];
        }
    });
    return next;
}

export default function ReportsClient() {
    const [group, setGroup] = useState<FeedbackGroup>("PDT GROUP");
    const [filters, setFilters] = useState<ReportFilters>({});
    const [draft, setDraft] = useState<ReportFilters>({});
    const [search, setSearch] = useState("");
    const [drill, setDrill] = useState<DrillScope | null>(null);
    const [textModal, setTextModal] = useState<{
        title: string;
        body?: string;
        excerpt?: string;
        feedbackId?: string;
        jobId?: string;
    } | null>(null);
    const [showFilters, setShowFilters] = useState(true);
    const [period, setPeriod] = useState<PeriodState>(defaultPeriod("month"));

    const appliedFilters = useMemo(
        () => ({ ...filters, feedback_group: group }),
        [filters, group],
    );

    const { data, isLoading, isFetching } = useReportSummary(appliedFilters);
    const conversationQuery = useReportConversation(textModal?.feedbackId, textModal?.jobId);
    const filterQuery = useReportFilterOptions({
        division: draft.division,
        zone: draft.zone,
        cluster: draft.cluster,
    });

    const linkedOptions = filterQuery.data?.data;
    const summaryOptions = data?.data?.filter_options;
    const geoScoped = Boolean(draft.division || draft.zone || draft.cluster);
    const filterOptions: FilterOptions = {
        ...EMPTY_FILTERS,
        ...summaryOptions,
        ...linkedOptions,
    };
    if (geoScoped) {
        filterOptions.clusters = linkedOptions?.rfmm_clusters ?? linkedOptions?.clusters ?? [];
        filterOptions.rfmm_clusters = filterOptions.clusters;
        filterOptions.fme_codes = linkedOptions?.fme_codes ?? [];
    }
    const source = data?.data?.source;
    const rfmmOptions = filterOptions.rfmm_clusters?.length
        ? filterOptions.rfmm_clusters
        : filterOptions.clusters;
    const productOptions = filterOptions.products || [];

    const rows = useMemo(
        () =>
            buildTagMatrixFromSummary(
                group,
                data?.data?.tags || [],
                data?.data?.categories || [],
                {
                    showSubTags: false,
                    categoryTotals: group !== "PDT GROUP",
                    search: appliedFilters.search,
                },
            ),
        [data?.data?.tags, data?.data?.categories, group, appliedFilters.search],
    );

    const columns = columnsForOverview();

    const applyFilters = () => {
        setFilters(sanitizeFilters(draft, search, datesForPeriod(period)));
        setDrill(null);
    };
    const clearFilters = () => {
        setDraft({});
        setFilters({});
        setSearch("");
        setPeriod(defaultPeriod("month"));
        setDrill(null);
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

    const switchGroup = (next: FeedbackGroup) => {
        setGroup(next);
        setDrill(null);
    };

    const openCell = (column: MatrixColumn, row: MatrixRow) => {
        if (column === "full_conversation") {
            setTextModal({
                title: COLUMN_LABELS.full_conversation,
                excerpt: row.feedback_excerpt,
                feedbackId: row.feedback_id,
                jobId: row.job_id,
            });
            return;
        }
        const bodies: Partial<Record<MatrixColumn, string | undefined>> = {
            feedback_summary_ai: row.feedback_summary_ai,
            feedback_excerpt: row.feedback_excerpt,
            file_name: row.file_name,
        };
        setTextModal({
            title: COLUMN_LABELS[column],
            body: bodies[column] || "",
        });
    };

    const isConversation = isFullConversationTitle(textModal?.title);
    const conversationBody = isConversation
        ? conversationQuery.data?.data?.full_conversation || ""
        : textModal?.body || "";
    const conversationTurns = isConversation
        ? parseConversationTurns(conversationBody).length
        : 0;
    let conversationSubtitle: string | undefined;
    if (isConversation && conversationQuery.isFetching) conversationSubtitle = "Loading…";
    else if (conversationTurns === 1) conversationSubtitle = "1 message";
    else if (conversationTurns > 1) conversationSubtitle = `${conversationTurns} messages`;

    return (
        <div className="p-6 max-w-[1600px] mx-auto min-h-screen text-slate-800">
            <div className="flex flex-wrap items-start justify-between gap-4 mb-6">
                <div>
                    <h1 className="text-2xl font-bold text-slate-900">Feedback Reports</h1>
                    <p className="text-sm text-slate-500 mt-1">
                        Start with the tag matrix. Click any count to see that tag by product, then read the full
                        summary, excerpt, and conversation.
                    </p>
                </div>
                <Button
                    variant="secondary"
                    onClick={() =>
                        exportMatrixCsv(`${group.replace(" ", "-").toLowerCase()}-tag-matrix.csv`, columns, rows)
                    }
                >
                    <FiDownload className="mr-2 h-4 w-4" />
                    Export CSV
                </Button>
            </div>

            <div className="flex flex-wrap gap-2 mb-4">
                {GROUP_TABS.map((tab) => (
                    <button
                        key={tab.id}
                        type="button"
                        onClick={() => switchGroup(tab.id)}
                        className={`rounded-md px-4 py-2 text-sm font-medium border transition-colors ${
                            group === tab.id
                                ? "bg-brand text-white border-brand"
                                : "bg-white text-slate-700 border-slate-200 hover:bg-slate-50"
                        }`}
                    >
                        {tab.label}
                    </button>
                ))}
            </div>

            {!drill ? (
                <div className="mb-5 rounded-lg border border-slate-200 bg-white p-4">
                    <button
                        type="button"
                        onClick={() => setShowFilters((open) => !open)}
                        className="flex w-full items-center justify-between text-sm font-semibold text-slate-700"
                    >
                        <span className="inline-flex items-center gap-2">
                            <FiFilter className="text-slate-400" />
                            Filters
                        </span>
                        <span className="text-xs font-medium text-brand">{showFilters ? "Hide" : "Show"}</span>
                    </button>
                    {showFilters ? (
                    <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
                        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-600">
                            Division
                            <Select
                                className="mt-1"
                                value={draft.division || "ALL"}
                                onChange={(value) => setDraft((prev) => applyLinkedSelect(prev, "division", value))}
                                options={withAll(filterOptions.divisions)}
                            />
                        </div>
                        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-600">
                            Zone
                            <Select
                                className="mt-1"
                                value={draft.zone || "ALL"}
                                onChange={(value) => setDraft((prev) => applyLinkedSelect(prev, "zone", value))}
                                options={withAll(filterOptions.zones)}
                            />
                        </div>
                        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-600">
                            RFMM Cluster
                            <Select
                                key={`rfmm-${draft.division || "all"}-${draft.zone || "all"}`}
                                className="mt-1"
                                value={draft.cluster || "ALL"}
                                onChange={(value) => setDraft((prev) => applyLinkedSelect(prev, "cluster", value))}
                                options={withAll(rfmmOptions)}
                            />
                        </div>
                        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-600">
                            FME
                            <Select
                                key={`fme-${draft.division || "all"}-${draft.zone || "all"}-${draft.cluster || "all"}`}
                                className="mt-1"
                                value={draft.fme_code || "ALL"}
                                onChange={(value) => setDraft((prev) => applySelect(prev, "fme_code", value))}
                                options={withAll(filterOptions.fme_codes || [])}
                            />
                        </div>
                        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-600">
                            Product
                            <Select
                                className="mt-1"
                                value={draft.product_name || "ALL"}
                                onChange={(value) => setDraft((prev) => applySelect(prev, "product_name", value))}
                                options={withAll(productOptions)}
                            />
                        </div>
                        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-600">
                            User type
                            <Select
                                className="mt-1"
                                value={draft.user_type || "ALL"}
                                onChange={(value) => setDraft((prev) => applySelect(prev, "user_type", value))}
                                options={withAll(filterOptions.user_types || [])}
                            />
                        </div>
                        <label className="text-[10px] font-bold uppercase tracking-wider text-slate-600">
                            Time period
                            <Select
                                className="mt-1"
                                value={period.kind}
                                onChange={(value) => selectPeriod(value as PeriodKind)}
                                options={PERIOD_TABS.map((tab) => ({ label: tab.label, value: tab.id }))}
                            />
                        </label>
                        {period.kind === "month" ? (
                            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-600">
                                Month
                                <input
                                    type="month"
                                    value={period.month || ""}
                                    onChange={(e) => updatePeriod({ month: e.target.value })}
                                    className="mt-1 h-9 w-full rounded border border-border bg-surface px-3 text-sm"
                                />
                            </label>
                        ) : null}
                        {period.kind === "quarter" || period.kind === "year" ? (
                            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-600">
                                Year
                                <input
                                    type="number"
                                    min="2000"
                                    max="2100"
                                    value={period.year || ""}
                                    onChange={(e) => updatePeriod({ year: e.target.value })}
                                    className="mt-1 h-9 w-full rounded border border-border bg-surface px-3 text-sm"
                                />
                            </label>
                        ) : null}
                        {period.kind === "quarter" ? (
                            <label className="text-[10px] font-bold uppercase tracking-wider text-slate-600">
                                Quarter
                                <Select
                                    className="mt-1"
                                    value={period.quarter || "1"}
                                    onChange={(value) => updatePeriod({ quarter: value })}
                                    options={QUARTER_OPTIONS}
                                />
                            </label>
                        ) : null}
                        <div>
                            <div className="mb-1 text-[10px] font-bold uppercase tracking-wider text-slate-600">
                                Search
                            </div>
                            <SearchInput value={search} onChange={setSearch} placeholder="Tag, product, file..." />
                        </div>
                        <div className="flex items-end gap-2">
                            <Button variant="secondary" onClick={clearFilters}>
                                Clear
                            </Button>
                            <Button onClick={applyFilters}>Apply filters</Button>
                        </div>
                    </div>
                    ) : null}
                </div>
            ) : null}

            {source === "unavailable" && (
                <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
                    {data?.message || "feedback_fact view is not available on this database yet."}
                </div>
            )}

            {isFetching && !isLoading && !drill && (
                <div className="mb-3 text-xs text-slate-500">Refreshing summary…</div>
            )}

            {isLoading && !drill ? (
                <div className="flex flex-col items-center justify-center rounded-lg border border-slate-200 bg-white py-24 text-text-disabled">
                    <LuLoader className="h-8 w-8 animate-spin mb-4 text-brand" />
                    <p className="text-sm">Loading tag summary...</p>
                </div>
            ) : drill ? (
                <ReportDrillView
                    drill={drill}
                    filters={appliedFilters}
                    onBack={() => setDrill(null)}
                    onDrill={setDrill}
                    onTextClick={openCell}
                />
            ) : (
                <ReportTable
                    key={group}
                    columns={columns}
                    rows={rows}
                    context={[{ label: "FEEDBACK GROUP", value: group }]}
                    itemLabel="tags"
                    onCountClick={(row) => {
                        if (row.drill) setDrill(row.drill);
                    }}
                />
            )}

            <ReportModal
                open={Boolean(textModal)}
                wide={isConversation}
                title={textModal?.title || ""}
                subtitle={isConversation ? conversationSubtitle : undefined}
                headerExtra={
                    textModal?.jobId ? (
                        <FileSourceLink jobId={textModal.jobId} fileName="Open source file" />
                    ) : null
                }
                onClose={() => setTextModal(null)}
            >
                {isConversation && conversationQuery.isFetching && !conversationBody ? (
                    <div className="flex items-center gap-2 py-8 text-sm text-slate-500">
                        <LuLoader className="h-4 w-4 animate-spin text-brand" />
                        Loading conversation…
                    </div>
                ) : isConversation && conversationQuery.isError ? (
                    <p className="text-sm text-red-600">Could not load this conversation.</p>
                ) : isConversation ? (
                    <ConversationThread
                        text={conversationBody || "Full conversation is not available for this row."}
                        excerpt={textModal?.excerpt || conversationQuery.data?.data?.feedback_excerpt || undefined}
                    />
                ) : (
                    <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-6 text-slate-800">
                        {textModal?.body}
                    </pre>
                )}
            </ReportModal>
        </div>
    );
}
