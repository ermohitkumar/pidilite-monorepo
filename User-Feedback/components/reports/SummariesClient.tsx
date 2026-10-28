"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { LuArrowLeft, LuLoader } from "react-icons/lu";

import { FileSourceLink } from "@/components/reports/FileSourceLink";
import { FormattedSummary } from "@/components/reports/FormattedSummary";
import { ReportModal } from "@/components/reports/ReportModal";
import { ReportTable } from "@/components/reports/ReportTable";
import { Button } from "@/components/ui/button";
import { MultiSelect } from "@/components/ui/MultiSelect";
import { Select } from "@/components/ui/Select";
import { useReportDetails, useReportFilterOptions, useReportProducts, useReportSummary } from "@/lib/hooks/reports";
import {
    buildCategoryTagRows,
    buildDetailRowsFromItems,
    buildLevelThreeRows,
    columnsForSummaryItems,
    columnsForSummaryTags,
    filtersForSummaryDrill,
    levelOneCategories,
} from "@/lib/reports/build";
import {
    datesForPeriod,
    defaultPeriod,
    filtersFromSearchParams,
    periodFromDateRange,
    type PeriodKind,
    type PeriodState,
} from "@/lib/reports/period";
import {
    COLUMN_LABELS,
    NO_PRODUCT_LABEL,
    type DrillScope,
    type MatrixColumn,
    type MatrixRow,
    type ReportFilters,
} from "@/lib/reports/types";

const PERIOD_TABS: { id: PeriodKind; label: string }[] = [
    { id: "all", label: "All" },
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

const TAG_COLUMNS = columnsForSummaryTags();
const THEME_COLUMNS: MatrixColumn[] = ["feedback_summary_ai", "feedback_tag", "feedback_count", "sentiment"];
const ITEM_COLUMNS = columnsForSummaryItems();
const ITEM_LABELS: Partial<Record<MatrixColumn, string>> = {
    feedback_excerpt: "Verbatim",
};
const DETAIL_PAGE_SIZES = [10, 20, 50];

type TagDrill = {
    category: string;
    tag: string;
    theme?: string;
};

type ScopeDraft = {
    product: string;
    zone: string[];
    cluster: string[];
    period: PeriodState;
};

function scopeFromFilters(filters: ReportFilters): ScopeDraft {
    return {
        product: filters.product_name || "ALL",
        zone: filters.zone || [],
        cluster: filters.cluster || [],
        period: periodFromDateRange(filters.start_date, filters.end_date),
    };
}

function filtersFromScope(scope: ScopeDraft): ReportFilters {
    const next: ReportFilters = { ...datesForPeriod(scope.period) };
    if (scope.product !== "ALL") next.product_name = scope.product;
    if (scope.zone.length) next.zone = scope.zone;
    if (scope.cluster.length) next.cluster = scope.cluster;
    return next;
}

type TextModal = {
    title: string;
    body?: string;
    jobId?: string;
};

function sameLabel(left?: string | null, right?: string | null): boolean {
    return (left || "").replace(/\s+/g, " ").trim().toLowerCase() === (right || "").replace(/\s+/g, " ").trim().toLowerCase();
}

export function ChoiceRow({
    label,
    value,
    options,
    onChange,
}: {
    label: string;
    value: string;
    options: { id: string; label: string }[];
    onChange: (id: string) => void;
}) {
    return (
        <div>
            <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</h2>
            <div className="flex flex-wrap gap-2">
                {options.map((option) => (
                    <button
                        key={option.id || "all"}
                        type="button"
                        onClick={() => onChange(option.id)}
                        className={`rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${
                            value === option.id
                                ? "border-transparent bg-brand-subtle text-brand"
                                : "border-slate-200 bg-white text-slate-600 hover:bg-slate-50"
                        }`}
                    >
                        {option.label}
                    </button>
                ))}
            </div>
        </div>
    );
}

function withAll(values: string[]): { label: string; value: string }[] {
    return [{ label: "All", value: "ALL" }, ...values.map((value) => ({ label: value, value }))];
}

function FilterSelect({
    label,
    value,
    onChange,
    options,
}: {
    label: string;
    value: string;
    onChange: (value: string) => void;
    options: string[];
}) {
    return (
        <label className="text-[12px] font-bold uppercase tracking-wider text-slate-600">
            {label}
            <Select className="mt-1" value={value || "ALL"} onChange={onChange} options={withAll(options)} />
        </label>
    );
}

function MultiFilterSelect({
    label,
    values,
    onChange,
    options,
}: {
    label: string;
    values: string[];
    onChange: (values: string[]) => void;
    options: string[];
}) {
    return (
        <div className="text-[12px] font-bold uppercase tracking-wider text-slate-600">
            {label}
            <MultiSelect className="mt-1" values={values} onChange={onChange} options={options} />
        </div>
    );
}

export function ScopeFilterBar({
    showProduct,
    product,
    productOptions,
    zone,
    zones,
    cluster,
    clusters,
    period,
    onProduct,
    onZone,
    onCluster,
    onPeriodKind,
    onPeriodPatch,
    onApply,
    onClear,
}: {
    showProduct: boolean;
    product: string;
    productOptions: string[];
    zone: string[];
    zones: string[];
    cluster: string[];
    clusters: string[];
    period: PeriodState;
    onProduct: (value: string) => void;
    onZone: (values: string[]) => void;
    onCluster: (values: string[]) => void;
    onPeriodKind: (kind: PeriodKind) => void;
    onPeriodPatch: (patch: Partial<PeriodState>) => void;
    onApply: () => void;
    onClear: () => void;
}) {
    return (
        <div className="grid grid-cols-2 gap-3 rounded-lg border border-slate-200 bg-white p-4 md:grid-cols-4 xl:grid-cols-6">
            {showProduct ? (
                <FilterSelect label="Product" value={product} onChange={onProduct} options={productOptions} />
            ) : null}
            <MultiFilterSelect label="Zone" values={zone} onChange={onZone} options={zones} />
            <MultiFilterSelect label="RFMM cluster" values={cluster} onChange={onCluster} options={clusters} />
            <label className="text-[12px] font-bold uppercase tracking-wider text-slate-600">
                Time period
                <Select
                    className="mt-1"
                    value={period.kind}
                    onChange={(value) => onPeriodKind(value as PeriodKind)}
                    options={PERIOD_TABS.map((tab) => ({ label: tab.label, value: tab.id }))}
                />
            </label>
            {period.kind === "month" ? (
                <label className="text-[12px] font-bold uppercase tracking-wider text-slate-600">
                    Month
                    <input
                        type="month"
                        value={period.month || ""}
                        onChange={(event) => onPeriodPatch({ month: event.target.value })}
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
                        onChange={(event) => onPeriodPatch({ year: event.target.value })}
                        className="mt-1 h-9 w-full rounded border border-border bg-surface px-3 text-sm"
                    />
                </label>
            ) : null}
            {period.kind === "quarter" ? (
                <label className="text-[12px] font-bold uppercase tracking-wider text-slate-600">
                    Quarter
                    <Select
                        className="mt-1"
                        value={period.quarter || "1"}
                        onChange={(value) => onPeriodPatch({ quarter: value })}
                        options={QUARTER_OPTIONS}
                    />
                </label>
            ) : null}
            <div className="flex items-end gap-2">
                <Button type="button" variant="secondary" onClick={onClear}>
                    Clear
                </Button>
                <Button type="button" onClick={onApply}>
                    Apply filters
                </Button>
            </div>
        </div>
    );
}

function SummaryItems({
    drill,
    scope,
    draft,
    productChoices,
    productOptions,
    zones,
    clusters,
    onProductChip,
    onProduct,
    onZone,
    onCluster,
    onPeriodKind,
    onPeriodPatch,
    onApply,
    onClear,
    onBack,
    onTextClick,
}: {
    drill: TagDrill;
    scope: ReportFilters;
    draft: ScopeDraft;
    productChoices: { id: string; label: string }[];
    productOptions: string[];
    zones: string[];
    clusters: string[];
    onProductChip: (value: string) => void;
    onProduct: (value: string) => void;
    onZone: (values: string[]) => void;
    onCluster: (values: string[]) => void;
    onPeriodKind: (kind: PeriodKind) => void;
    onPeriodPatch: (patch: Partial<PeriodState>) => void;
    onApply: () => void;
    onClear: () => void;
    onBack: () => void;
    onTextClick: (column: MatrixColumn, row: MatrixRow) => void;
}) {
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(20);
    const [sortBy, setSortBy] = useState<MatrixColumn | null>("call_datetime");
    const [sortDir, setSortDir] = useState<"asc" | "desc" | null>("desc");

    const productName = scope.product_name;

    useEffect(() => {
        setPage(1);
    }, [
        drill.category,
        drill.tag,
        drill.theme,
        productName,
        scope.zone,
        scope.cluster,
        scope.start_date,
        scope.end_date,
        pageSize,
        sortBy,
        sortDir,
    ]);

    const filters = useMemo(
        () => ({
            ...scope,
            ...filtersForSummaryDrill({
                category: drill.category,
                tag: drill.tag,
                theme: drill.theme,
                product: productName,
            }),
            page,
            page_size: pageSize,
            sort_by: sortBy || "call_datetime",
            sort_dir: sortDir || "desc",
        }),
        [drill.category, drill.tag, drill.theme, page, pageSize, productName, scope, sortBy, sortDir],
    );
    const detailsQuery = useReportDetails(filters, true);
    const detailScope = useMemo<DrillScope>(
        () => ({
            group: "PDT GROUP",
            level: "tag",
            feedback_category: drill.category,
            feedback_tag: drill.theme || drill.tag,
            product_name: productName,
        }),
        [drill.category, drill.tag, drill.theme, productName],
    );
    const rows = useMemo(
        () => buildDetailRowsFromItems(detailsQuery.data?.data?.items || [], detailScope),
        [detailsQuery.data?.data?.items, detailScope],
    );
    const meta = detailsQuery.data?.data?.metadata;
    const total = meta?.total_items || 0;
    const context = [
        { label: COLUMN_LABELS.feedback_category, value: drill.category },
        drill.tag && !sameLabel(drill.tag, drill.category)
            ? { label: COLUMN_LABELS.feedback_tag, value: drill.tag }
            : null,
        drill.theme && !sameLabel(drill.theme, drill.tag)
            ? { label: "Level 3 tag", value: drill.theme }
            : null,
        productName ? { label: COLUMN_LABELS.product_name, value: productName } : null,
        scope.zone?.length ? { label: "Zone", value: scope.zone.join(", ") } : null,
        scope.cluster?.length ? { label: "RFMM cluster", value: scope.cluster.join(", ") } : null,
    ].filter((chip): chip is { label: string; value: string } => Boolean(chip?.value));

    return (
        <div className="space-y-4">
            <div>
                <button
                    type="button"
                    onClick={onBack}
                    className="inline-flex items-center gap-2 text-sm font-medium text-brand hover:underline"
                >
                    <LuArrowLeft className="h-4 w-4" />
                    {drill.theme ? "Back to tags" : "Back to summary"}
                </button>
                <h2 className="mt-2 text-xl font-semibold text-slate-900">{drill.theme || drill.tag}</h2>
                <p className="mt-1 text-sm text-slate-500">
                    {total.toLocaleString()} feedback item{total === 1 ? "" : "s"}. Summary and verbatim for each one.
                </p>
            </div>
            <ChoiceRow
                label="Product"
                value={scope.product_name || "ALL"}
                options={productChoices}
                onChange={onProductChip}
            />
            <ScopeFilterBar
                showProduct={false}
                product={draft.product}
                productOptions={productOptions}
                zone={draft.zone}
                zones={zones}
                cluster={draft.cluster}
                clusters={clusters}
                period={draft.period}
                onProduct={onProduct}
                onZone={onZone}
                onCluster={onCluster}
                onPeriodKind={onPeriodKind}
                onPeriodPatch={onPeriodPatch}
                onApply={onApply}
                onClear={onClear}
            />
            <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500">Verbatim</h3>
            {detailsQuery.isLoading && !detailsQuery.data ? (
                <div className="flex flex-col items-center justify-center rounded-lg border border-slate-200 bg-white py-16 text-slate-400">
                    <LuLoader className="mb-4 h-8 w-8 animate-spin text-brand" />
                    <p className="text-sm">Loading feedback…</p>
                </div>
            ) : detailsQuery.isError ? (
                <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-10 text-center text-sm text-red-700">
                    Could not load feedback details.
                </div>
            ) : (
                <ReportTable
                    columns={ITEM_COLUMNS}
                    rows={rows}
                    context={context}
                    pinnedColumns={ITEM_COLUMNS}
                    columnLabels={ITEM_LABELS}
                    itemLabel="feedback items"
                    pageSizeOptions={DETAIL_PAGE_SIZES}
                    insightLevel
                    onTextClick={onTextClick}
                    serverMode={{
                        page: meta?.current_page || page,
                        pageSize: meta?.page_size || pageSize,
                        totalItems: total,
                        sortBy,
                        sortDir,
                        onPageChange: setPage,
                        onPageSizeChange: (size) => {
                            setPageSize(size);
                            setPage(1);
                        },
                        onSortChange: (next) => {
                            setSortBy(next?.column || "call_datetime");
                            setSortDir(next?.dir || "desc");
                            setPage(1);
                        },
                    }}
                />
            )}
        </div>
    );
}

export default function SummariesClient() {
    const searchParams = useSearchParams();
    const fromUrl = useMemo(() => filtersFromSearchParams(searchParams), [searchParams]);
    const categories = useMemo(() => levelOneCategories(), []);
    const [category, setCategory] = useState(() =>
        categories.some((item) => sameLabel(item, fromUrl.feedback_category))
            ? fromUrl.feedback_category || "ALL"
            : "ALL",
    );
    const [draft, setDraft] = useState<ScopeDraft>(() => scopeFromFilters(fromUrl));
    const [applied, setApplied] = useState<ScopeDraft>(() => scopeFromFilters(fromUrl));
    const [drill, setDrill] = useState<TagDrill | null>(() =>
        fromUrl.feedback_tag
            ? {
                category: fromUrl.feedback_category || fromUrl.feedback_tag,
                tag: fromUrl.feedback_tag,
            }
            : null,
    );
    const [textModal, setTextModal] = useState<TextModal | null>(null);

    const summaryFilters = useMemo(() => filtersFromScope(applied), [applied]);
    const summaryQuery = useReportSummary(summaryFilters);
    const productsQuery = useReportProducts({});
    const filterQuery = useReportFilterOptions({ zone: draft.zone.length ? draft.zone : undefined });
    const summaryTags = summaryQuery.data?.data?.tags || [];
    const rows = useMemo(
        () =>
            buildCategoryTagRows(summaryTags, {
                category: category === "ALL" ? undefined : category,
                themes: summaryQuery.data?.data?.themes || [],
            }),
        [category, summaryTags, summaryQuery.data?.data?.themes],
    );
    const levelThreeRows = useMemo(
        () => (drill ? buildLevelThreeRows(summaryTags, drill.tag, summaryQuery.data?.data?.themes || []) : []),
        [drill, summaryTags, summaryQuery.data?.data?.themes],
    );
    const categoryOptions = [
        { id: "ALL", label: "All" },
        ...categories.map((item) => ({ id: item, label: item })),
    ];
    const products = (productsQuery.data?.data?.items || []).filter(
        (item) => item.product_name && item.product_name !== NO_PRODUCT_LABEL && (item.feedback_count || 0) > 0,
    );
    const productNames = products.map((item) => item.product_name || "").filter(Boolean);
    if (draft.product !== "ALL" && !productNames.includes(draft.product)) productNames.unshift(draft.product);
    if (applied.product !== "ALL" && !productNames.includes(applied.product)) productNames.unshift(applied.product);
    const productOptions = [
        { id: "ALL", label: "All" },
        ...productNames.map((name) => ({ id: name, label: name })),
    ];
    const zones = filterQuery.data?.data?.zones || [];
    const clusters = filterQuery.data?.data?.rfmm_clusters?.length
        ? filterQuery.data.data.rfmm_clusters
        : filterQuery.data?.data?.clusters || [];
    const loading = summaryQuery.isLoading && !summaryQuery.data;

    const selectZone = (values: string[]) => {
        setDraft((prev) => ({ ...prev, zone: values, cluster: [] }));
    };
    const selectCluster = (values: string[]) => {
        setDraft((prev) => ({ ...prev, cluster: values }));
    };
    const selectPeriod = (kind: PeriodKind) => {
        setDraft((prev) => ({ ...prev, period: defaultPeriod(kind) }));
    };
    const patchPeriod = (patch: Partial<PeriodState>) => {
        setDraft((prev) => ({ ...prev, period: { ...prev.period, ...patch } }));
    };
    const selectDraftProduct = (value: string) => {
        setDraft((prev) => ({ ...prev, product: value === "ALL" ? "ALL" : value }));
    };
    const applyFilters = () => setApplied(draft);
    const clearFilters = () => {
        const cleared: ScopeDraft = {
            product: "ALL",
            zone: [],
            cluster: [],
            period: defaultPeriod("all"),
        };
        setDraft(cleared);
        setApplied(cleared);
    };

    const openCell = (column: MatrixColumn, row: MatrixRow) => {
        const bodies: Partial<Record<MatrixColumn, string | undefined>> = {
            feedback_summary_ai: row.feedback_summary_ai,
            feedback_excerpt: row.feedback_excerpt,
        };
        setTextModal({
            title: column === "feedback_excerpt" ? "Verbatim" : COLUMN_LABELS[column],
            body: bodies[column] || "",
            jobId: row.job_id,
        });
    };

    const selectCategory = (next: string) => {
        setCategory(next);
        setDrill(null);
    };
    const selectProduct = (next: string, closeDrill = false) => {
        const product = next === "ALL" ? "ALL" : next;
        setDraft((prev) => ({ ...prev, product }));
        setApplied((prev) => ({ ...prev, product }));
        if (closeDrill) setDrill(null);
    };

    return (
        <div className="p-6">
            <header className="mb-6">
                <h1 className="text-xl font-semibold text-slate-900">Summary</h1>
                <p className="text-sm text-slate-500">
                    Choose a feedback category and a product. Click a count to see the level 3 tags, then open verbatims.
                </p>
            </header>

            {drill?.theme || (drill && !loading && levelThreeRows.length === 0) ? (
                <SummaryItems
                    drill={drill}
                    scope={summaryFilters}
                    draft={draft}
                    productChoices={productOptions}
                    productOptions={productNames}
                    zones={zones}
                    clusters={clusters}
                    onProductChip={(next) => selectProduct(next)}
                    onProduct={selectDraftProduct}
                    onZone={selectZone}
                    onCluster={selectCluster}
                    onPeriodKind={selectPeriod}
                    onPeriodPatch={patchPeriod}
                    onApply={applyFilters}
                    onClear={clearFilters}
                    onBack={() =>
                        drill.theme ? setDrill({ category: drill.category, tag: drill.tag }) : setDrill(null)
                    }
                    onTextClick={openCell}
                />
            ) : drill ? (
                <div className="space-y-4">
                    <div>
                        <button
                            type="button"
                            onClick={() => setDrill(null)}
                            className="inline-flex items-center gap-2 text-sm font-medium text-brand hover:underline"
                        >
                            <LuArrowLeft className="h-4 w-4" />
                            Back to summary
                        </button>
                        <h2 className="mt-2 text-xl font-semibold text-slate-900">{drill.tag}</h2>
                        <p className="mt-1 text-sm text-slate-500">
                            Level 3 tags inside {drill.tag}. Click a count to open the feedback items.
                        </p>
                    </div>
                    <ChoiceRow
                        label="Product"
                        value={applied.product}
                        options={productOptions}
                        onChange={(next) => selectProduct(next)}
                    />
                    <ScopeFilterBar
                        showProduct={false}
                        product={draft.product}
                        productOptions={productNames}
                        zone={draft.zone}
                        zones={zones}
                        cluster={draft.cluster}
                        clusters={clusters}
                        period={draft.period}
                        onProduct={selectDraftProduct}
                        onZone={selectZone}
                        onCluster={selectCluster}
                        onPeriodKind={selectPeriod}
                        onPeriodPatch={patchPeriod}
                        onApply={applyFilters}
                        onClear={clearFilters}
                    />
                    {loading ? (
                        <div className="flex flex-col items-center justify-center rounded-lg border border-slate-200 bg-white py-16 text-text-disabled">
                            <LuLoader className="mb-4 h-8 w-8 animate-spin text-brand" />
                            <p className="text-sm">Loading tags…</p>
                        </div>
                    ) : (
                        <ReportTable
                            columns={THEME_COLUMNS}
                            rows={levelThreeRows}
                            pinnedColumns={THEME_COLUMNS}
                            context={[
                                { label: COLUMN_LABELS.feedback_category, value: drill.category },
                                { label: COLUMN_LABELS.feedback_tag, value: drill.tag },
                            ]}
                            itemLabel="tags"
                            onCountClick={(row) => {
                                if (!row.feedback_tag) return;
                                setDrill({ category: drill.category, tag: drill.tag, theme: row.feedback_tag });
                            }}
                            onTextClick={openCell}
                        />
                    )}
                </div>
            ) : (
                <div className="space-y-6">
                    <ChoiceRow
                        label="Feedback category"
                        value={category}
                        options={categoryOptions}
                        onChange={selectCategory}
                    />
                    <ChoiceRow
                        label="Product"
                        value={applied.product}
                        options={productOptions}
                        onChange={(next) => selectProduct(next, true)}
                    />
                    <ScopeFilterBar
                        showProduct={false}
                        product={draft.product}
                        productOptions={productNames}
                        zone={draft.zone}
                        zones={zones}
                        cluster={draft.cluster}
                        clusters={clusters}
                        period={draft.period}
                        onProduct={selectDraftProduct}
                        onZone={selectZone}
                        onCluster={selectCluster}
                        onPeriodKind={selectPeriod}
                        onPeriodPatch={patchPeriod}
                        onApply={applyFilters}
                        onClear={clearFilters}
                    />
                    {loading ? (
                        <div className="flex flex-col items-center justify-center rounded-lg border border-slate-200 bg-white py-16 text-text-disabled">
                            <LuLoader className="mb-4 h-8 w-8 animate-spin text-brand" />
                            <p className="text-sm">Loading summary…</p>
                        </div>
                    ) : (
                        <ReportTable
                            columns={TAG_COLUMNS}
                            rows={rows}
                            pinnedColumns={TAG_COLUMNS}
                            itemLabel="tags"
                            onCountClick={(row) => {
                                if (!row.feedback_tag || !row.drill) return;
                                setDrill({
                                    category: row.feedback_category || row.feedback_tag,
                                    tag: row.feedback_tag,
                                });
                            }}
                            onTextClick={openCell}
                        />
                    )}
                </div>
            )}

            <ReportModal
                open={Boolean(textModal)}
                title={textModal?.title || ""}
                headerExtra={
                    textModal?.jobId ? (
                        <FileSourceLink jobId={textModal.jobId} fileName="Open source file" />
                    ) : null
                }
                onClose={() => setTextModal(null)}
            >
                {textModal?.title === COLUMN_LABELS.feedback_summary_ai || textModal?.title.startsWith("Feedback summary") ? (
                    <FormattedSummary text={textModal?.body} emptyLabel="No summary for this row." />
                ) : (
                    <pre className="whitespace-pre-wrap break-words font-sans text-base leading-7 text-slate-800">
                        {textModal?.body || "No verbatim for this row."}
                    </pre>
                )}
            </ReportModal>
        </div>
    );
}
