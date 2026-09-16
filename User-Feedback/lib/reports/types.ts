export type FeedbackGroup = "PDT GROUP" | "USER GROUP" | "DEALER GROUP";

export const NO_PRODUCT_LABEL = "(No product)";

export type ReportView = "matrix" | "product" | "detail";

export type TaxonomyTag = {
    tag_id: number;
    feedback_group: string;
    feedback_category: string;
    feedback_tag: string;
    feedback_sub_tag?: string | null;
    description?: string | null;
};

export type FeedbackFactRow = {
    feedback_id?: string | null;
    job_id?: string | null;
    feedback_created_at?: string | null;
    feedback_group?: string | null;
    feedback_category?: string | null;
    feedback_tag?: string | null;
    feedback_sub_tag?: string | null;
    product_name?: string | null;
    product_id?: string | null;
    product_short_code?: string | null;
    feedback_summary_ai?: string | null;
    feedback_excerpt?: string | null;
    full_conversation?: string | null;
    full_conversation_raw?: string | null;
    full_conversation_truncated?: boolean;
    competitors_mentioned?: string | null;
    file_name?: string | null;
    call_date?: string | null;
    call_datetime?: string | null;
    language_code?: string | null;
    state?: string | null;
    division?: string | null;
    zone?: string | null;
    cluster?: string | null;
    rfmm_cluster?: string | null;
    town_city?: string | null;
    fme_code?: string | null;
    user_type?: string | null;
    data_source?: string | null;
    job_status?: string | null;
    audio_gcs_uri?: string | null;
};

export type FilterOptions = {
    divisions: string[];
    zones: string[];
    clusters: string[];
    rfmm_clusters?: string[];
    states: string[];
    products: string[];
    data_sources: string[];
    fme_codes: string[];
    user_types: string[];
};

export type FeedbackFactResponse = {
    success: boolean;
    message: string;
    data?: {
        items: FeedbackFactRow[];
        filter_options: FilterOptions;
        metadata?: {
            total_items?: number;
            returned_items?: number;
            truncated?: boolean;
            include_conversation?: boolean;
            current_page?: number;
            page_size?: number;
            total_pages?: number;
            has_next?: boolean;
            has_previous?: boolean;
            sort_by?: string | null;
            sort_dir?: string;
        };
        source?: string;
    };
    error?: string | null;
};

export type ReportSummaryTag = {
    feedback_category?: string | null;
    feedback_tag?: string | null;
    feedback_count: number;
    ai_summary?: string | null;
    summary_status?: string | null;
};

export type ReportSummaryCategory = {
    feedback_category?: string | null;
    feedback_count: number;
};

export type ReportSummaryResponse = {
    success: boolean;
    message: string;
    data?: {
        tags: ReportSummaryTag[];
        categories: ReportSummaryCategory[];
        total: number;
        filter_options?: FilterOptions;
        source?: string;
    };
    error?: string | null;
};

export type ReportProductCount = {
    product_name?: string | null;
    feedback_count: number;
};

export type ReportProductsResponse = {
    success: boolean;
    message: string;
    data?: {
        items: ReportProductCount[];
        total?: number;
        source?: string;
    };
    error?: string | null;
};

export type ReportDetailsResponse = {
    success: boolean;
    message: string;
    data?: {
        items: FeedbackFactRow[];
        metadata?: {
            total_items?: number;
            returned_items?: number;
            current_page?: number;
            page_size?: number;
            total_pages?: number;
            has_next?: boolean;
            has_previous?: boolean;
            sort_by?: string | null;
            sort_dir?: string;
        };
        source?: string;
    };
    error?: string | null;
};

export type ReportConversationResponse = {
    success: boolean;
    message: string;
    data?: {
        feedback_id?: string | null;
        job_id?: string | null;
        feedback_excerpt?: string | null;
        full_conversation?: string | null;
    };
    error?: string | null;
};

export type PeriodSummaryGrain =
    | "bde"
    | "rfmm"
    | "zone"
    | "division"
    | "product"
    | "tag"
    | "bde_pt"
    | "rfmm_pt"
    | "zone_pt"
    | "div_pt"
    | "bde_p"
    | "rfmm_p"
    | "zone_p"
    | "div_p"
    | "bde_t"
    | "rfmm_t"
    | "zone_t"
    | "div_t";

export type PeriodSummaryRecord = {
    id: string;
    grain: PeriodSummaryGrain | string;
    grain_key: string;
    grain_label?: string | null;
    parent_key?: string | null;
    period_type: string;
    period_key: string;
    period_start?: string | null;
    period_end?: string | null;
    summary_text?: string | null;
    highlights?: {
        call_count?: number;
        insight_count?: number;
        themes?: string[];
        products?: string[];
        risks?: string[];
        truncated?: boolean;
        coverage?: Record<string, unknown>;
        missing?: string[];
        errored?: string[];
        [key: string]: unknown;
    };
    source_kind?: string;
    source_count?: number;
    call_count?: number;
    insight_count?: number;
    status?: string;
    version?: number;
    generated_at?: string | null;
    error_message?: string | null;
};

export type PeriodSummaryResponse = {
    success: boolean;
    message: string;
    data?: {
        period_type: string;
        period_key: string;
        grain?: string | null;
        grain_key?: string | null;
        current?: PeriodSummaryRecord | null;
        previous?: PeriodSummaryRecord | null;
        product?: PeriodSummaryRecord | null;
        previous_product?: PeriodSummaryRecord | null;
        tag?: PeriodSummaryRecord | null;
        previous_tag?: PeriodSummaryRecord | null;
    };
    error?: string | null;
};

export type PeriodSummariesResponse = {
    success: boolean;
    message: string;
    data?: {
        period_type: string;
        period_key: string;
        grain: string;
        items: PeriodSummaryRecord[];
        products?: PeriodSummaryRecord[];
        tags?: PeriodSummaryRecord[];
        available_filters?: {
            divisions?: string[];
            zones?: string[];
            rfmm_clusters?: string[];
            fme_codes?: string[];
            products?: string[];
        };
    };
    error?: string | null;
};

export type ReportFilters = {
    feedback_group?: string;
    feedback_category?: string;
    feedback_tag?: string;
    feedback_sub_tag?: string;
    division?: string;
    zone?: string;
    cluster?: string;
    state?: string;
    product_name?: string;
    data_source?: string;
    fme_code?: string;
    user_type?: string;
    start_date?: string;
    end_date?: string;
    search?: string;
    sort_by?: string;
    sort_dir?: "asc" | "desc";
    page?: number;
    page_size?: number;
};

export type MatrixColumn =
    | "feedback_group"
    | "product_name"
    | "feedback_category"
    | "feedback_tag"
    | "feedback_sub_tag"
    | "feedback_count"
    | "feedback_summary_ai"
    | "feedback_excerpt"
    | "full_conversation"
    | "file_name"
    | "call_datetime"
    | "audio";

export type DrillLevel = "group" | "product" | "category" | "tag" | "sub_tag" | "item";

export type DrillScope = {
    group: FeedbackGroup;
    level: DrillLevel;
    product_name?: string;
    feedback_category?: string;
    feedback_tag?: string;
    feedback_sub_tag?: string;
    feedback_id?: string;
};

export type BreakdownRow = {
    label: string;
    count: number;
    drill: DrillScope;
};

export type MatrixRow = {
    kind: "data" | "total";
    feedback_group?: string;
    product_name?: string;
    feedback_category?: string;
    feedback_tag?: string;
    feedback_sub_tag?: string;
    feedback_count?: number | null;
    total_label?: string;
    feedback_summary_ai?: string;
    feedback_excerpt?: string;
    full_conversation?: string;
    full_conversation_raw?: string;
    competitors_mentioned?: string;
    file_name?: string;
    call_datetime?: string;
    job_id?: string;
    feedback_id?: string;
    drill?: DrillScope;
};

export const COLUMN_LABELS: Record<MatrixColumn, string> = {
    feedback_group: "FEEDBACK GROUP",
    product_name: "Product Name",
    feedback_category: "Feedback category",
    feedback_tag: "Feedback Tag",
    feedback_sub_tag: "Feedback sub Tag",
    feedback_count: "Feedback Count",
    feedback_summary_ai: "Feedback summary (AI generated)",
    feedback_excerpt: "Feedback voice recording (Excerpt)",
    full_conversation: "Full Conversation",
    file_name: "File name",
    call_datetime: "Date & time",
    audio: "Audio",
};

export const GROUP_TABS: { id: FeedbackGroup; label: string }[] = [
    { id: "PDT GROUP", label: "PDT Group" },
    { id: "USER GROUP", label: "User Group" },
    { id: "DEALER GROUP", label: "Dealer Group" },
];
