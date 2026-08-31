import { apiFetch } from './client';

type FetchParams = {
    page?: number;
    size?: number;
    search?: string;
    status?: string;
    sort_by?: string;
    sort_dir?: "asc" | "desc";
};

function buildQueryString(params: FetchParams): string {
    const searchParams = new URLSearchParams();
    if (params.page !== undefined) searchParams.append('page', params.page.toString());
    if (params.size !== undefined) searchParams.append('size', params.size.toString());
    if (params.search) searchParams.append('search', params.search);
    if (params.status && params.status !== 'ALL') searchParams.append('status', params.status);
    if (params.sort_by) searchParams.append('sort_by', params.sort_by);
    if (params.sort_dir) searchParams.append('sort_dir', params.sort_dir);
    return searchParams.toString();
}

export const fetchDashboardSummary = async () => {
    const res = await apiFetch('/api/v1/dashboard/summary');
    if (!res.ok) throw new Error('Failed to fetch dashboard summary');
    return res.json();
};

export const fetchBatches = async (params: FetchParams = {}) => {
    const qs = buildQueryString(params);
    const res = await apiFetch(`/api/v1/dashboard/batches?${qs}`);
    if (!res.ok) throw new Error('Failed to fetch batches');
    return res.json();
};

export const fetchBatchDetails = async (batchId: string, params: FetchParams = {}) => {
    const qs = buildQueryString(params);
    const res = await apiFetch(`/api/v1/dashboard/batches/${batchId}?${qs}`);
    if (!res.ok) throw new Error('Failed to fetch batch details');
    return res.json();
};

export const fetchJobs = async (params: FetchParams = {}) => {
    const qs = buildQueryString(params);
    const res = await apiFetch(`/api/v1/dashboard/jobs?${qs}`);
    if (!res.ok) throw new Error('Failed to fetch jobs');
    return res.json();
};

export const fetchJobInsights = async (jobId: string) => {
    const res = await apiFetch(`/api/v1/dashboard/jobs/${jobId}/insights`);
    if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.message || 'Failed to fetch job insights');
    }
    return res.json();
};
