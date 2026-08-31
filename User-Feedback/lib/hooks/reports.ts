import { useQuery } from "@tanstack/react-query";
import {
    fetchReportConversation,
    fetchReportDetails,
    fetchReportProducts,
    fetchReportSummary,
} from "@/lib/api/reports";
import type { ReportFilters } from "@/lib/reports/types";

export function useReportSummary(filters: ReportFilters) {
    return useQuery({
        queryKey: ["reportSummary", filters],
        queryFn: () => fetchReportSummary(filters),
        staleTime: 30_000,
        retry: 1,
    });
}

export function useReportProducts(filters: ReportFilters, enabled = true) {
    return useQuery({
        queryKey: ["reportProducts", filters],
        queryFn: () => fetchReportProducts(filters),
        enabled,
        staleTime: 30_000,
        retry: 1,
    });
}

export function useReportDetails(filters: ReportFilters, enabled = true) {
    return useQuery({
        queryKey: ["reportDetails", filters],
        queryFn: () => fetchReportDetails(filters),
        enabled,
        staleTime: 15_000,
        retry: 1,
    });
}

export function useReportConversation(feedbackId?: string, jobId?: string) {
    return useQuery({
        queryKey: ["reportConversation", feedbackId, jobId],
        queryFn: () => fetchReportConversation(feedbackId as string, jobId),
        enabled: Boolean(feedbackId),
        staleTime: 5 * 60_000,
        retry: 1,
    });
}
