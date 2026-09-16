"use client";

import { useEffect, useMemo, useState } from "react";
import { LuArrowLeft, LuLoader } from "react-icons/lu";

import { ReportTable } from "@/components/reports/ReportTable";
import { FormattedSummary } from "@/components/reports/FormattedSummary";
import { useReportDetails, useReportProducts } from "@/lib/hooks/reports";
import {
    buildDetailRowsFromItems,
    buildProductRowsFromCounts,
    columnsForDetail,
    columnsForProductDrill,
    drillPath,
    drillTitle,
    filtersForDrill,
} from "@/lib/reports/build";
import { COLUMN_LABELS } from "@/lib/reports/types";
import type {
    DrillScope,
    MatrixColumn,
    MatrixRow,
    PeriodSummaryRecord,
    ReportFilters,
} from "@/lib/reports/types";

const DETAIL_PAGE_SIZES = [10, 20, 50];

export function ReportDrillView({
    drill,
    filters,
    onBack,
    onDrill,
    onTextClick,
    tagNarrative,
    nationwideCaption,
    periodProducts = [],
}: Readonly<{
    drill: DrillScope;
    filters: ReportFilters;
    onBack: () => void;
    onDrill: (next: DrillScope) => void;
    onTextClick: (column: MatrixColumn, row: MatrixRow) => void;
    tagNarrative?: string;
    nationwideCaption?: boolean;
    periodProducts?: PeriodSummaryRecord[];
}>) {
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(20);
    const [sortBy, setSortBy] = useState<MatrixColumn | null>("call_datetime");
    const [sortDir, setSortDir] = useState<"asc" | "desc" | null>("desc");

    const drillFilters = useMemo(() => filtersForDrill(filters, drill), [filters, drill]);
    const wantProducts = !drill.product_name;
    const productsQuery = useReportProducts(drillFilters, wantProducts);
    const productItems = productsQuery.data?.data?.items || [];
    const showProductBreakdown = wantProducts && productItems.length > 0;
    const productsReady = !wantProducts || !productsQuery.isLoading;
    const showDetail = productsReady && !showProductBreakdown;

    const detailsQuery = useReportDetails(
        {
            ...drillFilters,
            page,
            page_size: pageSize,
            sort_by: sortBy || "call_datetime",
            sort_dir: sortDir || "desc",
        },
        showDetail,
    );

    useEffect(() => {
        setPage(1);
    }, [drill, filters, pageSize, sortBy, sortDir]);

    const productRows = useMemo(
        () => buildProductRowsFromCounts(drill, productItems, periodProducts),
        [drill, productItems, periodProducts],
    );
    const detailItems = detailsQuery.data?.data?.items || [];
    const detailRows = useMemo(
        () => buildDetailRowsFromItems(detailItems, drill),
        [detailItems, drill],
    );
    const detailMeta = detailsQuery.data?.data?.metadata;
    const itemCount = showProductBreakdown
        ? productsQuery.data?.data?.total ?? productItems.reduce((sum, row) => sum + (row.feedback_count || 0), 0)
        : detailMeta?.total_items ?? 0;
    const includeProduct = Boolean(drill.product_name) || detailRows.some((row) => row.product_name);
    const showHeaderNarratives = !drill.product_name;
    const crumbs = drillPath(drill);
    const context = [
        { label: COLUMN_LABELS.feedback_group, value: drill.group },
        drill.product_name ? { label: COLUMN_LABELS.product_name, value: drill.product_name } : null,
        drill.feedback_category
            ? { label: COLUMN_LABELS.feedback_category, value: drill.feedback_category }
            : null,
        drill.feedback_tag ? { label: COLUMN_LABELS.feedback_tag, value: drill.feedback_tag } : null,
    ].filter((chip): chip is { label: string; value: string } => Boolean(chip));

    const handleBack = () => {
        if (!drill.product_name) {
            onBack();
            return;
        }
        let level: DrillScope["level"] = "group";
        if (drill.feedback_sub_tag) level = "sub_tag";
        else if (drill.feedback_tag) level = "tag";
        else if (drill.feedback_category) level = "category";
        onDrill({
            group: drill.group,
            level,
            feedback_category: drill.feedback_category,
            feedback_tag: drill.feedback_tag,
            feedback_sub_tag: drill.feedback_sub_tag,
        });
    };

    const loading = (wantProducts && productsQuery.isLoading) || (showDetail && detailsQuery.isLoading);
    const fetching = (wantProducts && productsQuery.isFetching) || (showDetail && detailsQuery.isFetching);

    return (
        <div className="space-y-6">
            <div className="rounded-xl border border-slate-200 bg-white px-5 py-4">
                <button
                    type="button"
                    onClick={handleBack}
                    className="inline-flex items-center gap-2 text-sm font-medium text-brand hover:underline"
                >
                    <LuArrowLeft className="h-4 w-4" />
                    {drill.product_name ? "Back to product breakdown" : "Back to tag matrix"}
                </button>
                <div className="mt-3 flex flex-wrap items-center gap-1.5 text-sm text-slate-500">
                    {crumbs.map((crumb, index) => (
                        <span key={`${crumb}-${index}`} className="inline-flex items-center gap-1.5">
                            {index > 0 ? <span className="text-slate-300">/</span> : null}
                            <span className={index === crumbs.length - 1 ? "font-semibold text-slate-900" : ""}>
                                {crumb}
                            </span>
                        </span>
                    ))}
                </div>
                <h2 className="mt-2 text-xl font-bold text-slate-900">{drillTitle(drill)}</h2>
                {showHeaderNarratives && tagNarrative ? (
                    <div className="mt-3 rounded-lg border border-slate-100 bg-slate-50 px-3 py-3">
                        <p className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                            Tag summary
                        </p>
                        <FormattedSummary text={tagNarrative} />
                    </div>
                ) : null}
                {showHeaderNarratives && nationwideCaption ? (
                    <p className="mt-2 text-xs text-slate-500">
                        Narrative is all India for this period; counts follow your filters.
                    </p>
                ) : null}
                <p className="mt-1 text-sm text-slate-500">
                    {itemCount} feedback item{itemCount === 1 ? "" : "s"} in this selection.
                    {showProductBreakdown
                        ? " Counts below are split by product — click a count to open full detail."
                        : " Full conversations, summaries, and excerpts are listed below."}
                </p>
            </div>

            {fetching && !loading ? (
                <div className="text-xs text-slate-500">Refreshing this page…</div>
            ) : null}

            {loading ? (
                <div className="flex flex-col items-center justify-center rounded-lg border border-slate-200 bg-white py-24 text-slate-400">
                    <LuLoader className="h-8 w-8 animate-spin mb-4 text-brand" />
                    <p className="text-sm">Loading {showProductBreakdown || wantProducts ? "breakdown" : "details"}…</p>
                </div>
            ) : null}

            {!loading && showProductBreakdown ? (
                <section>
                    <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">
                        Breakdown by product
                    </h3>
                    <ReportTable
                        key={`product-${drill.level}-${drill.feedback_tag || ""}`}
                        columns={columnsForProductDrill(drill)}
                        rows={productRows}
                        context={context}
                        itemLabel="product rows"
                        onCountClick={(row) => row.drill && onDrill(row.drill)}
                        onTextClick={onTextClick}
                    />
                </section>
            ) : null}

            {!loading && showDetail ? (
            <section>
                <h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-500">
                    Full detail
                </h3>
                {detailsQuery.isError ? (
                    <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-10 text-center text-sm text-red-700">
                        Could not load feedback details. Try again, or go back and reopen this count.
                    </div>
                ) : detailRows.length === 0 ? (
                    <div className="rounded-xl border border-slate-200 bg-white px-4 py-10 text-center text-sm text-slate-500">
                        No feedback rows for this count.
                    </div>
                ) : (
                    <ReportTable
                        key={`detail-${drill.level}-${drill.product_name || ""}-${drill.feedback_tag || ""}`}
                        columns={columnsForDetail(drill, includeProduct)}
                        rows={detailRows}
                        context={context}
                        itemLabel="feedback items"
                        pageSizeOptions={DETAIL_PAGE_SIZES}
                        optionalColumns={["call_datetime", "file_name", "audio"]}
                        defaultHiddenColumns={["file_name", "audio"]}
                        settingsStorageKey="reports-detail-hidden-columns-v2"
                        onTextClick={onTextClick}
                        serverMode={{
                            page: detailMeta?.current_page || page,
                            pageSize: detailMeta?.page_size || pageSize,
                            totalItems: detailMeta?.total_items || 0,
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
            </section>
            ) : null}
        </div>
    );
}
