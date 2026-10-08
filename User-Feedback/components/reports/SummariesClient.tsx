"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { FiFilter } from "react-icons/fi";
import { LuLoader } from "react-icons/lu";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/Select";
import { PeriodSummaryCard } from "@/components/reports/PeriodSummaryCard";
import { usePeriodSummaries, usePeriodSummary, useReportFilterOptions } from "@/lib/hooks/reports";
import {
    datesForPeriod,
    defaultPeriod,
    filtersFromSearchParams,
    groupFromGrainKey,
    hasVisibleSummary,
    insightsHref,
    periodFromDateRange,
    restrictToAvailable,
    type GroupFilter,
    type PeriodKind,
    type PeriodState,
} from "@/lib/reports/period";
import {
    GROUP_FILTER_TABS,
    GROUP_TABS,
    displayGroupLabel,
    type FeedbackGroup,
    type FilterOptions,
    type PeriodSummaryRecord,
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
        <div className="text-[10px] font-bold uppercase tracking-wider text-slate-600">
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

function tagsForGroup(tags: PeriodSummaryRecord[], group: FeedbackGroup, viewingAll: boolean): PeriodSummaryRecord[] {
    return tags.filter((item) => {
        const found = groupFromGrainKey(item.grain_key);
        if (found) return found === group;
        return !viewingAll;
    });
}

function GroupTagSection({
    group,
    label,
    tags,
    loading,
    insightsLink,
}: {
    group: FeedbackGroup;
    label: string;
    tags: PeriodSummaryRecord[];
    loading: boolean;
    insightsLink: string;
}) {
    const visible = tags.filter(hasVisibleSummary);
    return (
        <section className="rounded-lg border border-slate-200 bg-white p-4">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                <h2 className="text-sm font-semibold text-slate-800">{label}</h2>
                <Link
                    href={insightsLink}
                    className="text-xs font-medium text-brand hover:underline"
                >
                    View insights
                </Link>
            </div>
            {loading ? (
                <p className="text-sm text-slate-500">Loading tags…</p>
            ) : visible.length === 0 ? (
                <p className="text-sm text-slate-500">No stored tag summaries for this group yet.</p>
            ) : (
                <div className="space-y-3">
                    {visible.map((item) => (
                        <PeriodSummaryCard
                            key={`${group}-${item.grain}-${item.grain_key}-${item.period_key}`}
                            title={item.grain_label || item.grain_key}
                            record={item}
                            emptyLabel="No summary."
                            hideMeta
                        />
                    ))}
                </div>
            )}
        </section>
    );
}

function groupFromUrl(value?: string): GroupFilter {
    if (value === "USER GROUP" || value === "DEALER GROUP" || value === "PDT GROUP") return value;
    return "ALL";
}

export default function SummariesClient() {
    const searchParams = useSearchParams();
    const fromUrl = useMemo(() => filtersFromSearchParams(searchParams), [searchParams]);
    const initialPeriod = useMemo(
        () => periodFromDateRange(fromUrl.start_date, fromUrl.end_date),
        [fromUrl.end_date, fromUrl.start_date],
    );
    const initialFilters = useMemo(() => {
        const dates = fromUrl.start_date && fromUrl.end_date
            ? { start_date: fromUrl.start_date, end_date: fromUrl.end_date }
            : datesForPeriod(initialPeriod);
        const next: ReportFilters = { ...fromUrl, ...dates };
        delete next.feedback_group;
        return next;
    }, [fromUrl, initialPeriod]);
    const [group, setGroup] = useState<GroupFilter>(groupFromUrl(fromUrl.feedback_group));
    const [draft, setDraft] = useState<ReportFilters>(initialFilters);
    const [filters, setFilters] = useState<ReportFilters>(initialFilters);
    const [period, setPeriod] = useState<PeriodState>(initialPeriod);
    const [showFilters, setShowFilters] = useState(true);

    const filterQuery = useReportFilterOptions({
        division: draft.division,
        zone: draft.zone,
        cluster: draft.cluster,
    });
    const appliedFilters = useMemo(() => {
        const next: ReportFilters = { ...filters };
        if (group !== "ALL") next.feedback_group = group;
        else delete next.feedback_group;
        return next;
    }, [filters, group]);
    const summaryQuery = usePeriodSummary(appliedFilters);
    const listQuery = usePeriodSummaries(appliedFilters);

    const filterOptions: FilterOptions = {
        ...EMPTY_FILTERS,
        ...filterQuery.data?.data,
    };
    const available = listQuery.data?.data?.available_filters;
    const rfmmLive = filterOptions.rfmm_clusters?.length
        ? filterOptions.rfmm_clusters
        : filterOptions.clusters;
    const divisionOptions = restrictToAvailable(filterOptions.divisions, available?.divisions);
    const zoneOptions = restrictToAvailable(filterOptions.zones, available?.zones);
    const rfmmOptions = restrictToAvailable(rfmmLive, available?.rfmm_clusters);
    const fmeOptions = restrictToAvailable(filterOptions.fme_codes || [], available?.fme_codes);
    const productOptions = filterOptions.products || [];

    const applyFilters = () => setFilters(sanitizeFilters(draft, datesForPeriod(period)));
    const clearFilters = () => {
        const next = defaultPeriod("month");
        setDraft({});
        setPeriod(next);
        setFilters(datesForPeriod(next));
        setGroup("ALL");
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

    const current = summaryQuery.data?.data?.current;
    const productSummary = summaryQuery.data?.data?.product;
    const tags = (listQuery.data?.data?.tags || []).filter(hasVisibleSummary);
    const viewingAll = group === "ALL";
    const groupsToShow = viewingAll ? GROUP_TABS : GROUP_TABS.filter((tab) => tab.id === group);
    const insightsLink = insightsHref(appliedFilters);
    const locationLabel = [
        appliedFilters.division,
        appliedFilters.zone,
        appliedFilters.cluster,
        appliedFilters.fme_code,
        appliedFilters.product_name,
    ].filter(Boolean).join(" · ") || "All India";

    return (
        <div className="p-6">
            <div className="mb-4 flex items-start justify-between gap-3">
                <div>
                    <h1 className="text-xl font-semibold text-slate-900">Reports</h1>
                    <p className="text-sm text-slate-500">
                        Tag summaries by feedback group. Open insights to see counts and drill into site visits.
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <Button variant="secondary" onClick={() => setShowFilters((value) => !value)}>
                        <FiFilter className="mr-2 h-4 w-4" />
                        {showFilters ? "Hide filters" : "Show filters"}
                    </Button>
                    <Link href={insightsLink}>
                        <Button type="button">View insights</Button>
                    </Link>
                </div>
            </div>

            <div className="mb-4 flex flex-wrap gap-2">
                {GROUP_FILTER_TABS.map((tab) => (
                    <button
                        key={tab.id}
                        type="button"
                        onClick={() => setGroup(tab.id)}
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

            {showFilters ? (
                <div className="mb-5 grid grid-cols-2 gap-3 rounded-lg border border-slate-200 bg-white p-4 md:grid-cols-4 xl:grid-cols-6">
                    <OptionalSelect
                        label="Division"
                        value={draft.division}
                        onChange={(value) => setDraft((prev) => applyLinkedSelect(prev, "division", value))}
                        options={divisionOptions}
                    />
                    <OptionalSelect
                        label="Zone"
                        value={draft.zone}
                        onChange={(value) => setDraft((prev) => applyLinkedSelect(prev, "zone", value))}
                        options={zoneOptions}
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
                        options={fmeOptions}
                    />
                    <OptionalSelect
                        label="Product"
                        value={draft.product_name}
                        onChange={(value) => setDraft((prev) => applySelect(prev, "product_name", value))}
                        options={productOptions}
                    />
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
                    <div className="flex items-end gap-2">
                        <Button type="button" variant="secondary" onClick={clearFilters}>
                            Clear
                        </Button>
                        <Button type="button" onClick={applyFilters}>Apply filters</Button>
                    </div>
                </div>
            ) : null}

            <p className="mb-3 text-xs text-slate-500">
                {locationLabel}
                {viewingAll ? " · all feedback groups" : ` · ${displayGroupLabel(group)}`}
            </p>

            {listQuery.isLoading && !listQuery.data ? (
                <div className="flex flex-col items-center justify-center rounded-lg border border-slate-200 bg-white py-16 text-text-disabled">
                    <LuLoader className="mb-4 h-8 w-8 animate-spin text-brand" />
                    <p className="text-sm">Loading summaries…</p>
                </div>
            ) : (
                <div className="space-y-4">
                    {!viewingAll && hasVisibleSummary(current) ? (
                        <PeriodSummaryCard
                            title="Location summary"
                            record={current}
                            emptyLabel="No stored summary for this filter yet."
                        />
                    ) : null}
                    {appliedFilters.product_name && hasVisibleSummary(productSummary) ? (
                        <PeriodSummaryCard
                            title={`${appliedFilters.product_name} summary`}
                            record={productSummary}
                            emptyLabel="No stored product summary for this filter yet."
                        />
                    ) : null}
                    {groupsToShow.map((tab) => (
                        <GroupTagSection
                            key={tab.id}
                            group={tab.id}
                            label={`${tab.label} tags`}
                            tags={tagsForGroup(tags, tab.id, viewingAll)}
                            loading={listQuery.isFetching && !listQuery.data}
                            insightsLink={insightsHref({ ...appliedFilters, feedback_group: tab.id })}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}
