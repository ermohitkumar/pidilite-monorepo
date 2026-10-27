"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useMemo, useState } from "react";
import { FiDownload } from "react-icons/fi";
import { LuLoader } from "react-icons/lu";

import { ConversationThread } from "@/components/reports/ConversationThread";
import { FileSourceLink } from "@/components/reports/FileSourceLink";
import { FormattedSummary } from "@/components/reports/FormattedSummary";
import { ReportDrillView } from "@/components/reports/ReportDrillView";
import { ReportModal } from "@/components/reports/ReportModal";
import { exportMatrixCsv, ReportTable } from "@/components/reports/ReportTable";
import { ChoiceRow, ScopeFilterBar } from "@/components/reports/SummariesClient";
import { Button } from "@/components/ui/button";
import { useReportConversation, useReportFilterOptions, useReportProducts, useReportSummary, usePeriodSummaries } from "@/lib/hooks/reports";
import {
    buildCategoryTagRows,
    categoryForTagDrill,
    columnsForSummaryTags,
    groupForCategory,
    levelOneCategories,
    tagLabelsMatch,
} from "@/lib/reports/build";
import { isFullConversationTitle, parseConversationTurns } from "@/lib/reports/conversation";
import {
    datesForPeriod,
    defaultPeriod,
    filtersFromSearchParams,
    periodFromDateRange,
    summariesHref,
    type PeriodKind,
    type PeriodState,
} from "@/lib/reports/period";
import {
    COLUMN_LABELS,
    NO_PRODUCT_LABEL,
    type DrillScope,
    type FeedbackGroup,
    type MatrixColumn,
    type MatrixRow,
    type ReportFilters,
} from "@/lib/reports/types";

function scopeFilters(
    product: string | undefined,
    zone: string | undefined,
    cluster: string | undefined,
    dates: Pick<ReportFilters, "start_date" | "end_date">,
): ReportFilters {
    const next: ReportFilters = { ...dates };
    if (product && product !== "ALL") next.product_name = product;
    if (zone && zone !== "ALL") next.zone = zone;
    if (cluster && cluster !== "ALL") next.cluster = cluster;
    return next;
}

export default function ReportsClient() {
    const searchParams = useSearchParams();
    const fromUrl = useMemo(() => filtersFromSearchParams(searchParams), [searchParams]);
    const initialPeriod = useMemo(
        () => periodFromDateRange(fromUrl.start_date, fromUrl.end_date),
        [fromUrl.end_date, fromUrl.start_date],
    );
    const initialFilters = useMemo(() => {
        const dates = fromUrl.start_date && fromUrl.end_date ? {
            start_date: fromUrl.start_date,
            end_date: fromUrl.end_date,
        } : datesForPeriod(initialPeriod);
        const next: ReportFilters = { ...fromUrl, ...dates };
        delete next.feedback_group;
        return next;
    }, [fromUrl, initialPeriod]);
    const [period, setPeriod] = useState<PeriodState>(initialPeriod);
    const [filters, setFilters] = useState<ReportFilters>(initialFilters);
    const [draft, setDraft] = useState<ReportFilters>(initialFilters);
    const openVerbatim = searchParams.get("verbatim") === "1";
    const [drill, setDrill] = useState<DrillScope | null>(() => {
        if (!fromUrl.feedback_tag && !(openVerbatim && fromUrl.product_name)) return null;
        const urlGroup = fromUrl.feedback_group;
        const drillGroup: FeedbackGroup =
            urlGroup === "USER GROUP" || urlGroup === "DEALER GROUP" || urlGroup === "PDT GROUP"
                ? urlGroup
                : groupForCategory(fromUrl.feedback_category, fromUrl.feedback_tag);
        return {
            group: drillGroup,
            level: fromUrl.feedback_tag ? "tag" : "product",
            feedback_tag: fromUrl.feedback_tag,
            feedback_category: categoryForTagDrill(fromUrl.feedback_category, fromUrl.feedback_tag),
            product_name: fromUrl.product_name,
        };
    });
    const [textModal, setTextModal] = useState<{
        title: string;
        body?: string;
        excerpt?: string;
        feedbackId?: string;
        jobId?: string;
    } | null>(null);
    const [category, setCategory] = useState("ALL");

    const appliedFilters = filters;
    const summariesBackHref = useMemo(() => {
        const { feedback_group: _feedbackGroup, ...next } = appliedFilters;
        return summariesHref(next);
    }, [appliedFilters]);

    const { data, isLoading, isFetching } = useReportSummary(appliedFilters);
    const periodListQuery = usePeriodSummaries({
        division: appliedFilters.division,
        zone: appliedFilters.zone,
        cluster: appliedFilters.cluster,
        fme_code: appliedFilters.fme_code,
        product_name: appliedFilters.product_name,
        start_date: appliedFilters.start_date,
        end_date: appliedFilters.end_date,
    });
    const conversationQuery = useReportConversation(textModal?.feedbackId, textModal?.jobId);
    const filterQuery = useReportFilterOptions({ zone: draft.zone });
    const productsQuery = useReportProducts({});

    const linkedOptions = filterQuery.data?.data;
    const source = data?.data?.source;
    const zoneOptions = linkedOptions?.zones || [];
    const rfmmOptions = linkedOptions?.rfmm_clusters?.length
        ? linkedOptions.rfmm_clusters
        : linkedOptions?.clusters || [];
    const productNames = (productsQuery.data?.data?.items || [])
        .filter((item) => item.product_name && item.product_name !== NO_PRODUCT_LABEL && (item.feedback_count || 0) > 0)
        .map((item) => item.product_name || "")
        .filter(Boolean);
    if (draft.product_name && !productNames.includes(draft.product_name)) productNames.unshift(draft.product_name);
    const productChoices = [
        { id: "ALL", label: "All" },
        ...productNames.map((name) => ({ id: name, label: name })),
    ];
    const categoryOptions = [
        { id: "ALL", label: "All" },
        ...levelOneCategories().map((label) => ({ id: label, label })),
    ];

    const rows = useMemo(
        () =>
            buildCategoryTagRows(data?.data?.tags || [], {
                category: category === "ALL" ? undefined : category,
                periodTags: periodListQuery.data?.data?.tags || [],
                themes: data?.data?.themes || [],
            }),
        [category, data?.data?.tags, data?.data?.themes, periodListQuery.data?.data?.tags],
    );

    const columns = columnsForSummaryTags();
    const selectedTagNarrative = useMemo(() => {
        if (drill?.feedback_tag) {
            const tagName = drill.feedback_tag;
            const match = (data?.data?.tags || []).find((row) => tagLabelsMatch(row.feedback_tag, tagName));
            if (match?.summary_status === "error") return "Updating…";
            const fromCounts = (match?.ai_summary || "").trim();
            if (fromCounts) return fromCounts;
            const periodMatch = (periodListQuery.data?.data?.tags || []).find((row) =>
                tagLabelsMatch(row.grain_label || row.grain_key, tagName),
            );
            if (periodMatch?.status === "error") return "Updating…";
            return (periodMatch?.summary_text || "").trim() || undefined;
        }
        if (!drill?.product_name) return undefined;
        const productName = drill.product_name;
        const periodMatch = (periodListQuery.data?.data?.products || []).find((row) =>
            tagLabelsMatch(row.grain_label || row.grain_key, productName),
        );
        if (periodMatch?.status === "error") return "Updating…";
        return (periodMatch?.summary_text || "").trim() || undefined;
    }, [drill?.feedback_tag, drill?.product_name, data?.data?.tags, periodListQuery.data?.data?.tags, periodListQuery.data?.data?.products]);
    const selectedTagHighlights = useMemo(() => {
        if (drill?.feedback_tag) {
            const tagName = drill.feedback_tag;
            const periodMatch = (periodListQuery.data?.data?.tags || []).find((row) =>
                tagLabelsMatch(row.grain_label || row.grain_key, tagName),
            );
            return periodMatch?.highlights;
        }
        if (!drill?.product_name) return undefined;
        const productName = drill.product_name;
        const periodMatch = (periodListQuery.data?.data?.products || []).find((row) =>
            tagLabelsMatch(row.grain_label || row.grain_key, productName),
        );
        return periodMatch?.highlights;
    }, [drill?.feedback_tag, drill?.product_name, periodListQuery.data?.data?.tags, periodListQuery.data?.data?.products]);

    const applyFilters = () => {
        setFilters(scopeFilters(draft.product_name, draft.zone, draft.cluster, datesForPeriod(period)));
        setDrill(null);
    };
    const clearFilters = () => {
        const next = defaultPeriod("all");
        const dates = datesForPeriod(next);
        setDraft({});
        setFilters(dates);
        setPeriod(next);
        setCategory("ALL");
        setDrill(null);
    };
    const selectProduct = (next: string) => {
        const product = next === "ALL" ? undefined : next;
        setDraft((prev) => ({ ...prev, product_name: product }));
        setFilters((prev) => scopeFilters(product, prev.zone, prev.cluster, {
            start_date: prev.start_date,
            end_date: prev.end_date,
        }));
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
    const isAiSummary = textModal?.title === COLUMN_LABELS.feedback_summary_ai;
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
                    <Link href={summariesBackHref} className="text-xs font-medium text-brand hover:underline">
                        ← Back to summary
                    </Link>
                    <h1 className="mt-1 text-2xl font-bold text-slate-900">Feedback</h1>
                    <p className="text-sm text-slate-500 mt-1">
                        Counts follow your current filters. Click a count to drill into site visits.
                    </p>
                </div>
                <Button
                    variant="secondary"
                    onClick={() => exportMatrixCsv("feedback-tag-matrix.csv", columns, rows)}
                >
                    <FiDownload className="mr-2 h-4 w-4" />
                    Export CSV
                </Button>
            </div>

            {!drill ? (
                <div className="mb-5 space-y-6">
                    <ChoiceRow
                        label="Feedback category"
                        value={categoryOptions.some((option) => option.id === category) ? category : "ALL"}
                        options={categoryOptions}
                        onChange={(next) => {
                            setCategory(next);
                            setDrill(null);
                        }}
                    />
                    <ChoiceRow
                        label="Product"
                        value={filters.product_name || "ALL"}
                        options={productChoices}
                        onChange={selectProduct}
                    />
                    <ScopeFilterBar
                        showProduct={false}
                        product={draft.product_name || "ALL"}
                        productOptions={productNames}
                        zone={draft.zone || ""}
                        zones={zoneOptions}
                        cluster={draft.cluster || ""}
                        clusters={rfmmOptions}
                        period={period}
                        onProduct={selectProduct}
                        onZone={(value) =>
                            setDraft((prev) => ({
                                ...prev,
                                zone: !value || value === "ALL" ? undefined : value,
                                cluster: undefined,
                            }))
                        }
                        onCluster={(value) =>
                            setDraft((prev) => ({
                                ...prev,
                                cluster: !value || value === "ALL" ? undefined : value,
                            }))
                        }
                        onPeriodKind={selectPeriod}
                        onPeriodPatch={updatePeriod}
                        onApply={applyFilters}
                        onClear={clearFilters}
                    />
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

            {isLoading && !data && !drill ? (
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
                    tagNarrative={selectedTagNarrative}
                    tagHighlights={selectedTagHighlights}
                    periodProducts={periodListQuery.data?.data?.products || []}
                    periodTags={periodListQuery.data?.data?.product_tags || periodListQuery.data?.data?.tags || []}
                    verbatim={openVerbatim}
                />
            ) : (
                <>
                    <ReportTable
                        columns={columns}
                        rows={rows}
                        pinnedColumns={columns}
                        itemLabel="tags"
                        onCountClick={(row) => {
                            if (row.drill) setDrill(row.drill);
                        }}
                        onTextClick={openCell}
                    />
                </>
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
                ) : isAiSummary ? (
                    <FormattedSummary text={textModal?.body} emptyLabel="No summary for this row." />
                ) : (
                    <pre className="whitespace-pre-wrap break-words font-sans text-base leading-7 text-slate-800">
                        {textModal?.body}
                    </pre>
                )}
            </ReportModal>
        </div>
    );
}
