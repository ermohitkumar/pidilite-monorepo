import { useQuery } from '@tanstack/react-query';
import {
    fetchDashboardSummary,
    fetchBatches,
    fetchJobs,
    fetchBatchDetails,
    fetchJobInsights
} from '../api/monitor';

export type FetchParams = {
    page?: number;
    size?: number;
    search?: string;
    status?: string;
    sort_by?: string;
    sort_dir?: "asc" | "desc";
};

export const useDashboardSummary = () => {
    return useQuery({
        queryKey: ['dashboardSummary'],
        queryFn: fetchDashboardSummary,
        refetchInterval: 5000,
    });
};

export const useBatches = (params: FetchParams = {}, initialData?: any) => {
    return useQuery({
        queryKey: ['batches', params],
        queryFn: () => fetchBatches(params),
        initialData,
        refetchInterval: 5000,
    });
};

export const useJobs = (params: FetchParams = {}, initialData?: any) => {
    return useQuery({
        queryKey: ['jobs', params],
        queryFn: () => fetchJobs(params),
        initialData,
        refetchInterval: 5000,
    });
};

export const useBatchDetails = (batchId: string, params: FetchParams = {}, initialData?: any) => {
    return useQuery({
        queryKey: ['batchDetails', batchId, params],
        queryFn: () => fetchBatchDetails(batchId, params),
        initialData,
        refetchInterval: 5000,
    });
};

export const useFileInsights = (fileId: string) => {
    return useQuery({
        queryKey: ['fileInsights', fileId],
        queryFn: () => fetchJobInsights(fileId),
        refetchInterval: (query) => {
            const data = query?.state?.data as { data?: { status?: string; feedbacks?: unknown[] } } | undefined;
            const status = data?.data?.status;
            if (status === 'COMPLETED' || status === 'FAILED' || status === 'ERROR') return false;
            return data?.data?.feedbacks?.length ? false : 5000;
        },
    });
};
