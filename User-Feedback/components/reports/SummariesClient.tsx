"use client";

import { useMemo, useState } from "react";
import { FiFilter } from "react-icons/fi";
import { LuLoader } from "react-icons/lu";

import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/Select";
import { PeriodSummaryCard, PERIOD_GRAIN_LABEL } from "@/components/reports/PeriodSummaryCard";
import { usePeriodSummaries, usePeriodSummary, useReportFilterOptions } from "@/lib/hooks/reports";
import { datesForPeriod, defaultPeriod, hasVisibleSummary, restrictToAvailable, type PeriodKind, type PeriodState } from "@/lib/reports/period";
import { GROUP_TABS, type FeedbackGroup, type FilterOptions, type PeriodSummaryRecord, type ReportFilters } from "@/lib/reports/types";

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

export default function SummariesClient() {
    const [group, setGroup] = useState<FeedbackGroup>("PDT GROUP");
    const [draft, setDraft] = useState<ReportFilters>({});
    const [filters, setFilters] = useState<ReportFilters>(datesForPeriod(defaultPeriod("month")));
    const [period, setPeriod] = useState<PeriodState>(defaultPeriod("month"));
    const [showFilters, setShowFilters] = useState(true);

    const filterQuery = useReportFilterOptions({
        division: draft.division,
        zone: draft.zone,
        cluster: draft.cluster,
    });
    const appliedFilters = { ...filters, feedback_group: group };
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
    // Keep every catalog product even when no product-grain summary exists yet.
    const productOptions = filterOptions.products || [];

    const appliedLabel = useMemo(() => {
        const grain = summaryQuery.data?.data?.grain;
        const key = summaryQuery.data?.data?.grain_key;
        if (grain && key) return `${PERIOD_GRAIN_LABEL[grain] || grain}: ${key}`;
        return "All divisions";
    }, [summaryQuery.data?.data?.grain, summaryQuery.data?.data?.grain_key]);

    const applyFilters = () => setFilters(sanitizeFilters(draft, datesForPeriod(period)));
    const clearFilters = () => {
        const next = defaultPeriod("month");
        setDraft({});
        setPeriod(next);
        setFilters(datesForPeriod(next));
    };
    const selectPeriod = (kind: PeriodKind) => {
        const next = defaultPeriod(kind);
        const dates = datesForPeriod(next);
        setPeriod(next);
        setDraft((prev) => ({ ...prev, ...dates }));
        setFilters((prev) => sanitizeFilters(prev, dates));
    };
    const updatePeriod = (patch: Partial<PeriodState>) => {
        const next = { ...period, ...patch };
        const dates = datesForPeriod(next);
        setPeriod(next);
        setDraft((prev) => ({ ...prev, ...dates }));
        setFilters((prev) => sanitizeFilters(prev, dates));
    };

    const current = summaryQuery.data?.data?.current;
    const previous = summaryQuery.data?.data?.previous;
    const product = summaryQuery.data?.data?.product;
    const previousProduct = summaryQuery.data?.data?.previous_product;
    const tag = summaryQuery.data?.data?.tag;
    const previousTag = summaryQuery.data?.data?.previous_tag;
    const items = (listQuery.data?.data?.items || []).filter(hasVisibleSummary);
    const products = (listQuery.data?.data?.products || []).filter(hasVisibleSummary);
    const tags = (listQuery.data?.data?.tags || []).filter(hasVisibleSummary);
    const listGrain = listQuery.data?.data?.grain || "division";

    return (
        <div className="p-6">
            <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                    <h1 className="text-xl font-semibold text-slate-900">Period summaries</h1>
                    <p className="text-sm text-slate-500">
                        Stored BDE → RFMM → zone → division narratives, plus product and tag summaries for the selected group.
                    </p>
                </div>
                <Button variant="secondary" onClick={() => setShowFilters((value) => !value)}>
                    <FiFilter className="mr-2 h-4 w-4" />
                    {showFilters ? "Hide filters" : "Show filters"}
                </Button>
            </div>

            <div className="mb-4 flex flex-wrap gap-2">
                {GROUP_TABS.map((tab) => (
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
                        <Button variant="secondary" onClick={clearFilters}>
                            Clear
                        </Button>
                        <Button onClick={applyFilters}>Apply filters</Button>
                    </div>
                </div>
            ) : null}

            <p className="mb-3 text-xs text-slate-500">Showing {appliedLabel}</p>

            {summaryQuery.isLoading ? (
                <div className="flex flex-col items-center justify-center rounded-lg border border-slate-200 bg-white py-16 text-text-disabled">
                    <LuLoader className="mb-4 h-8 w-8 animate-spin text-brand" />
                    <p className="text-sm">Loading period summaries…</p>
                </div>
            ) : (
                <div className="space-y-4">
                    {hasVisibleSummary(current) ? (
                        <PeriodSummaryCard
                            title="Current period"
                            record={current}
                            emptyLabel="No stored summary for this filter yet."
                        />
                    ) : null}
                    {hasVisibleSummary(previous) ? (
                        <PeriodSummaryCard title="Previous period" record={previous} emptyLabel="No previous period summary." />
                    ) : null}
                    {hasVisibleSummary(product) ? (
                        <PeriodSummaryCard title="Product" record={product} emptyLabel="No product summary." />
                    ) : null}
                    {hasVisibleSummary(previousProduct) ? (
                        <PeriodSummaryCard title="Previous product period" record={previousProduct} emptyLabel="No previous product summary." />
                    ) : null}
                    {hasVisibleSummary(tag) ? <PeriodSummaryCard title="Tag" record={tag} emptyLabel="No tag summary." /> : null}
                    {hasVisibleSummary(previousTag) ? (
                        <PeriodSummaryCard title="Previous tag period" record={previousTag} emptyLabel="No previous tag summary." />
                    ) : null}

                    <section>
                        <h2 className="mb-2 text-sm font-semibold text-slate-800">
                            {PERIOD_GRAIN_LABEL[listGrain] || listGrain} summaries
                        </h2>
                        {listQuery.isLoading ? (
                            <p className="text-sm text-slate-500">Loading list…</p>
                        ) : items.length === 0 ? (
                            <p className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
                                No stored summaries for this period. They appear after the nightly reports job runs.
                            </p>
                        ) : (
                            <div className="grid gap-3 md:grid-cols-2">
                                {items.map((item: PeriodSummaryRecord) => (
                                    <PeriodSummaryCard
                                        key={`${item.grain}-${item.grain_key}-${item.period_key}`}
                                        title={item.grain_label || item.grain_key}
                                        record={item}
                                        emptyLabel="No summary."
                                    />
                                ))}
                            </div>
                        )}
                    </section>

                    <section>
                        <h2 className="mb-2 text-sm font-semibold text-slate-800">Product summaries</h2>
                        <p className="mb-2 text-xs text-slate-500">
                            Product narratives for this period{appliedFilters.division || appliedFilters.zone || appliedFilters.cluster || appliedFilters.fme_code ? " at the selected location" : " nationwide"}.
                        </p>
                        {listQuery.isLoading ? (
                            <p className="text-sm text-slate-500">Loading products…</p>
                        ) : products.length === 0 ? (
                            <p className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
                                No stored product summaries for this period yet.
                            </p>
                        ) : (
                            <div className="grid gap-3 md:grid-cols-2">
                                {products.map((item: PeriodSummaryRecord) => (
                                    <PeriodSummaryCard
                                        key={`${item.grain}-${item.grain_key}-${item.period_key}`}
                                        title={item.grain_label || item.grain_key}
                                        record={item}
                                        emptyLabel="No summary."
                                    />
                                ))}
                            </div>
                        )}
                    </section>

                    <section>
                        <h2 className="mb-2 text-sm font-semibold text-slate-800">Tag summaries</h2>
                        <p className="mb-2 text-xs text-slate-500">
                            Tag narratives for this period{appliedFilters.division || appliedFilters.zone || appliedFilters.cluster || appliedFilters.fme_code ? " at the selected location" : " nationwide"}.
                        </p>
                        {listQuery.isLoading ? (
                            <p className="text-sm text-slate-500">Loading tags…</p>
                        ) : tags.length === 0 ? (
                            <p className="rounded-lg border border-slate-200 bg-slate-50 p-4 text-sm text-slate-500">
                                No stored tag summaries for this period yet.
                            </p>
                        ) : (
                            <div className="grid gap-3 md:grid-cols-2">
                                {tags.map((item: PeriodSummaryRecord) => (
                                    <PeriodSummaryCard
                                        key={`${item.grain}-${item.grain_key}-${item.period_key}`}
                                        title={item.grain_label || item.grain_key}
                                        record={item}
                                        emptyLabel="No summary."
                                    />
                                ))}
                            </div>
                        )}
                    </section>
                </div>
            )}
        </div>
    );
}
