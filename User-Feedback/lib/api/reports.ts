import { apiFetch } from "./client";
import type {
    FilterOptions,
    ReportConversationResponse,
    ReportDetailsResponse,
    ReportFilters,
    ReportProductsResponse,
    ReportSummaryResponse,
    PeriodSummariesResponse,
    PeriodSummaryResponse,
} from "@/lib/reports/types";

function buildQuery(params: Record<string, unknown>): string {
    const searchParams = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
        if (value === undefined || value === null || value === "" || value === "ALL") return;
        searchParams.append(key, String(value));
    });
    return searchParams.toString();
}

export async function fetchReportFilterOptions(
    params: Pick<ReportFilters, "division" | "zone" | "cluster"> = {},
): Promise<{ success: boolean; data?: FilterOptions }> {
    const qs = buildQuery(params);
    const res = await apiFetch(`/api/v1/reports/filter-options${qs ? `?${qs}` : ""}`);
    if (!res.ok) throw new Error("Failed to fetch report filter options");
    return res.json();
}

export async function fetchReportSummary(
    params: ReportFilters = {},
): Promise<ReportSummaryResponse> {
    const qs = buildQuery(params);
    const res = await apiFetch(`/api/v1/reports/summary${qs ? `?${qs}` : ""}`);
    if (!res.ok) throw new Error("Failed to fetch report summary");
    return res.json();
}

export async function fetchReportProducts(
    params: ReportFilters = {},
): Promise<ReportProductsResponse> {
    const qs = buildQuery(params);
    const res = await apiFetch(`/api/v1/reports/products${qs ? `?${qs}` : ""}`);
    if (!res.ok) throw new Error("Failed to fetch report products");
    return res.json();
}

export async function fetchReportDetails(
    params: ReportFilters = {},
): Promise<ReportDetailsResponse> {
    const qs = buildQuery(params);
    const res = await apiFetch(`/api/v1/reports/details${qs ? `?${qs}` : ""}`);
    if (!res.ok) throw new Error("Failed to fetch report details");
    return res.json();
}

export async function fetchReportConversation(
    feedbackId: string,
    jobId?: string,
): Promise<ReportConversationResponse> {
    const qs = buildQuery({ feedback_id: feedbackId, job_id: jobId });
    const res = await apiFetch(`/api/v1/reports/conversation?${qs}`);
    if (!res.ok) throw new Error("Failed to fetch conversation");
    return res.json();
}

export async function fetchPeriodSummary(
    params: Pick<
        ReportFilters,
        | "division"
        | "zone"
        | "cluster"
        | "fme_code"
        | "product_name"
        | "feedback_tag"
        | "feedback_group"
        | "start_date"
        | "end_date"
    > = {},
): Promise<PeriodSummaryResponse> {
    const qs = buildQuery({ ...params, include_previous: true });
    const res = await apiFetch(`/api/v1/reports/period-summary${qs ? `?${qs}` : ""}`);
    if (!res.ok) throw new Error("Failed to fetch period summary");
    return res.json();
}

export async function fetchPeriodSummaries(
    params: Pick<
        ReportFilters,
        "division" | "zone" | "cluster" | "fme_code" | "product_name" | "feedback_group" | "start_date" | "end_date"
    > = {},
): Promise<PeriodSummariesResponse> {
    const qs = buildQuery(params);
    const res = await apiFetch(`/api/v1/reports/period-summaries${qs ? `?${qs}` : ""}`);
    if (!res.ok) throw new Error("Failed to fetch period summaries");
    return res.json();
}
