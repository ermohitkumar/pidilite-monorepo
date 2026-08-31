// Shared Enums
export type BatchStatus = 'PENDING' | 'PROCESSING' | 'COMPLETED' | 'PARTIAL_SUCCESS' | 'FAILED';
export type JobStatus = 'PENDING' | 'BATCHED' | 'STT_SUBMITTED' | 'STT_COMPLETED' | 'PROCESSING' | 'COMPLETED' | 'FAILED' | 'ERROR';

// Generic API Response Wrappers
export interface PaginationMeta {
    current_page: number;
    page_size: number;
    total_items: number;
    total_pages: number;
    has_next: boolean;
    has_previous: boolean;
    completed_jobs?: number;
    failed_jobs?: number;
}

export interface ApiResponse<T> {
    success: boolean;
    message: string;
    data: T;
    error?: string | null;
}

export interface PaginatedData<T> {
    items: T[];
    metadata: PaginationMeta;
}

// 1. Dashboard Summary Model
export interface DashboardSummary {
    total_batches: number;
    active_batches: {
        count: number;
        active_jobs: number;
    };
    files_processed_24h: {
        count: number;
        success_rate: number;
    };
    failed_files: {
        count: number;
    };
}

// 2. Batch Model
export interface Batch {
    batch_id: string;
    batch_number: number;
    status: BatchStatus;
    total_jobs: number;
    completed_jobs: number;
    failed_jobs: number;
    created_at: string;
    completed_at: string | null;
}

// 3. Job Model
export interface Job {
    job_id: string;
    batch_id?: string;
    batch_number?: number | null;
    file_name: string;
    status: JobStatus;
    created_at: string;
    has_insights: boolean;
    error_message?: string | null;
}

// 3.5 Specific Single Batch Detail Response
export interface BatchJobsMeta extends PaginationMeta {
    completed_jobs: number;
    failed_jobs: number;
}

export interface BatchDetail {
    batch_info: Batch;
    jobs: {
        items: Job[];
        metadata: BatchJobsMeta;
    };
}

export interface FeedbackItem {
    product_name?: string;
    category_name?: string;
    tag_name?: string;
    group_type?: string;
    verbatim_quote?: string;
    remarks?: string;
    sentiment_label?: string;
    sentiment_score?: number;
    contractor_profile?: string;
}

export interface SummaryData {
    overall_sentiment_label?: string;
    overall_sentiment_score?: number;
    summary_product?: string;
    summary_price_schemes?: string;
    summary_quality?: string;
    summary_service?: string;
}

export interface InsightsData {
    job_id: string;
    file_name: string;
    status?: string;
    error_message?: string | null;
    empty_reason?: string | null;
    raw_transcript_text?: string | null;
    translated_text?: string | null;
    normalized_text?: string | null;
    summary?: SummaryData | null;
    feedbacks: FeedbackItem[];
    generated_at?: string;
}