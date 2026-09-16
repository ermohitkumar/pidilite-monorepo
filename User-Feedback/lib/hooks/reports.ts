import { useQuery } from "@tanstack/react-query";
import {
    fetchReportConversation,
    fetchReportDetails,
    fetchReportFilterOptions,
    fetchReportProducts,
    fetchReportSummary,
    fetchPeriodSummaries,
    fetchPeriodSummary,
} from "@/lib/api/reports";
import type { ReportFilters } from "@/lib/reports/types";

export function useReportFilterOptions(filters: Pick<ReportFilters, "division" | "zone" | "cluster">) {
    return useQuery({
        queryKey: ["reportFilterOptions", filters.division, filters.zone, filters.cluster],
        queryFn: () => fetchReportFilterOptions(filters),
        staleTime: 60_000,
        retry: 1,
        placeholderData: (previousData, previousQuery) => {
            if (!previousData?.data) return previousData;
            const prevKey = previousQuery?.queryKey ?? [];
            const divisionChanged = prevKey[1] !== filters.division;
            const zoneChanged = prevKey[2] !== filters.zone;
            const clusterChanged = prevKey[3] !== filters.cluster;
            if (!divisionChanged && !zoneChanged && !clusterChanged) return previousData;
            return {
                ...previousData,
                data: {
                    ...previousData.data,
                    ...(divisionChanged || zoneChanged
                        ? { clusters: [], rfmm_clusters: [], fme_codes: [] }
                        : {}),
                    ...(clusterChanged ? { fme_codes: [] } : {}),
                },
            };
        },
    });
}

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

export function usePeriodSummary(filters: ReportFilters, enabled = true) {
    return useQuery({
        queryKey: ["periodSummary", filters],
        queryFn: () => fetchPeriodSummary(filters),
        enabled,
        staleTime: 30_000,
        retry: 1,
    });
}

export function usePeriodSummaries(filters: ReportFilters, enabled = true) {
    return useQuery({
        queryKey: ["periodSummaries", filters],
        queryFn: () => fetchPeriodSummaries(filters),
        enabled,
        staleTime: 30_000,
        retry: 1,
    });
}
