import type { Batch, InsightsData, Job, JobStatus } from './types';

export const BATCHES: Batch[] = [
    { batch_id: 'BATCH-001', batch_number: 1, status: 'PROCESSING', completed_jobs: 8, failed_jobs: 0, total_jobs: 15, created_at: '2026-05-13T10:00:00Z', completed_at: null },
    { batch_id: 'BATCH-002', batch_number: 2, status: 'COMPLETED', completed_jobs: 24, failed_jobs: 0, total_jobs: 24, created_at: '2026-05-13T09:00:00Z', completed_at: '2026-05-13T10:45:11Z' },
    { batch_id: 'BATCH-003', batch_number: 3, status: 'PARTIAL_SUCCESS', completed_jobs: 4, failed_jobs: 1, total_jobs: 5, created_at: '2026-05-13T08:00:00Z', completed_at: '2026-05-13T11:05:00Z' },
    { batch_id: 'BATCH-004', batch_number: 4, status: 'PENDING', completed_jobs: 0, failed_jobs: 0, total_jobs: 50, created_at: '2026-05-13T07:00:00Z', completed_at: null },
    { batch_id: 'BATCH-005', batch_number: 5, status: 'COMPLETED', completed_jobs: 12, failed_jobs: 0, total_jobs: 12, created_at: '2026-05-12T10:00:00Z', completed_at: '2026-05-12T14:20:00Z' },
];

export const BATCH_JOBS: Record<string, Job[]> = {
    'BATCH-001': [
        { job_id: 'job-1', batch_id: 'BATCH-001', batch_number: 1, file_name: 'Q3_Earnings_Call_Raw.wav', status: 'PROCESSING', created_at: '2026-05-13T10:00:00Z', has_insights: false },
        { job_id: 'job-2', batch_id: 'BATCH-001', batch_number: 1, file_name: 'Customer_Interview_Alpha.mp3', status: 'COMPLETED', created_at: '2026-05-13T09:00:00Z', has_insights: true },
        { job_id: 'job-3', batch_id: 'BATCH-001', batch_number: 1, file_name: 'Investor_Update_Oct.wav', status: 'COMPLETED', created_at: '2026-05-13T09:15:00Z', has_insights: true },
        { job_id: 'job-4', batch_id: 'BATCH-001', batch_number: 1, file_name: 'Board_Briefing_Q3.flac', status: 'PENDING', created_at: '2026-05-13T10:30:00Z', has_insights: false },
    ]
};

export const FILES: Job[] = [
    { job_id: 'job-1', batch_id: 'BATCH-001', batch_number: 1, file_name: 'Q3_Earnings_Call_Raw.wav', status: 'PROCESSING', created_at: '2026-05-13T10:00:00Z', has_insights: false },
    { job_id: 'job-2', batch_id: 'BATCH-002', batch_number: 2, file_name: 'Customer_Interview_Alpha.mp3', status: 'COMPLETED', created_at: '2026-05-13T09:00:00Z', has_insights: true },
    { job_id: 'job-3', batch_id: 'BATCH-003', batch_number: 3, file_name: 'Investor_Update_Oct.wav', status: 'COMPLETED', created_at: '2026-05-13T09:15:00Z', has_insights: true },
    { job_id: 'job-4', batch_id: 'BATCH-004', batch_number: 4, file_name: 'Board_Briefing_Q3.flac', status: 'PENDING', created_at: '2026-05-13T10:30:00Z', has_insights: false },
    { job_id: 'job-5', batch_id: 'BATCH-005', batch_number: 5, file_name: 'Analyst_Call_Final.wav', status: 'PENDING', created_at: '2026-05-13T11:00:00Z', has_insights: false },
];

export const INSIGHTS: InsightsData = {
    job_id: 'job_8f3d9c2e-7b1a-4e5f-9d2c-1a2b3c4d5e6f',
    file_name: 'Q3_Sales_Call_North.wav',
    normalized_text: 'Good morning everyone, let\'s discuss the Fevicol SH sales for the northern region. We saw strong growth in Delhi NCR this quarter. Dr. Fixit also performed well in tier-2 cities.',
    summary: {
        overall_sentiment_label: 'POSITIVE',
        overall_sentiment_score: 0.8,
        summary_product: 'Product: Xper',
    },
    feedbacks: [
        {
            category_name: 'Packaging',
            tag_name: 'Box Design',
            verbatim_quote: '"The new packaging is really hard to open, but the product inside is great."',
            remarks: 'Packaging design is frustrating, but product quality meets expectations.',
            sentiment_label: 'NEUTRAL'
        },
        {
            category_name: 'Product',
            tag_name: 'Core Build',
            verbatim_quote: '"I love the durability of this item. It\'s been my daily driver for months."',
            remarks: 'High satisfaction with product durability and daily usability.',
            sentiment_label: 'POSITIVE'
        },
        {
            category_name: 'Price',
            tag_name: 'Upgrades',
            verbatim_quote: '"Pricing feels a bit steep compared to last year\'s model."',
            remarks: 'Negative perception of price increase year-over-year.',
            sentiment_label: 'POSITIVE' // Let's keep it POSITIVE as per image (green border)
        },
        {
            category_name: 'Service',
            tag_name: 'Resolution',
            verbatim_quote: '"Support resolved my issue quickly, very satisfied."',
            remarks: 'Positive experience with support resolution time.',
            sentiment_label: 'POSITIVE'
        },
        {
            category_name: 'Product',
            tag_name: 'Aesthetics',
            verbatim_quote: '"Could use more color options for the premium tier."',
            remarks: 'Request for additional color variations in premium offerings.',
            sentiment_label: 'POSITIVE'
        },
        {
            category_name: 'Service',
            tag_name: 'Delivery',
            verbatim_quote: '"Delivery was delayed by two days without warning."',
            remarks: 'Frustration regarding uncommunicated delivery delays.',
            sentiment_label: 'NEGATIVE'
        },
        {
            category_name: 'Product',
            tag_name: 'App Power',
            verbatim_quote: '"The app drains battery faster since the last update."',
            remarks: 'Recent update introduced battery optimization issues.',
            sentiment_label: 'NEGATIVE'
        },
        {
            category_name: 'Price',
            tag_name: 'Promo UX',
            verbatim_quote: '"Love the new scheme but finding where to apply the code is a mess."',
            remarks: 'Positive on discount but poor UX for code application.',
            sentiment_label: 'POSITIVE'
        }
    ],
    generated_at: '2026-04-30T10:45:00Z',
};