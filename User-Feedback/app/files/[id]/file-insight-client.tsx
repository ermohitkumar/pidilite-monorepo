"use client";

import { useState } from 'react';
import { LuExpand } from 'react-icons/lu';
import { AudioPlayer } from '@/components/reports/AudioPlayer';
import { ConversationThread } from '@/components/reports/ConversationThread';
import { ReportModal } from '@/components/reports/ReportModal';
import { JobStatusBadge } from '@/components/monitor/JobStatusBadge';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { useFileInsights } from '@/lib/hooks/queries';
import type { FeedbackItem, InsightsData, JobStatus } from '@/lib/monitor/types';

function isInsightsData(value: unknown): value is InsightsData {
    return Boolean(value && typeof value === 'object' && 'job_id' in (value as InsightsData));
}

function TranscriptPane({
    title,
    text,
    empty,
}: Readonly<{ title: string; text?: string | null; empty: string }>) {
    return (
        <div className="flex min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-surface">
            <div className="shrink-0 border-b border-border px-4 py-3">
                <h2 className="text-[13px] font-semibold uppercase tracking-wide text-text">{title}</h2>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto app-scrollbar">
                {text ? (
                    <ConversationThread text={text} />
                ) : (
                    <p className="px-4 py-6 text-sm text-text-subtle">{empty}</p>
                )}
            </div>
        </div>
    );
}

export default function FileInsightClient({ fileId }: Readonly<{ fileId: string }>) {
    const { data: response, isLoading, isError, error } = useFileInsights(fileId);
    const [transcriptOpen, setTranscriptOpen] = useState(false);
    const activeData = isInsightsData(response?.data) ? response.data : null;

    if (isLoading && !activeData) {
        return <div className="p-8 text-center text-text-subtle">Loading file…</div>;
    }

    if (isError) {
        return (
            <div className="p-8 text-center text-status-red-fg">
                {error instanceof Error ? error.message : 'Could not load this file.'}
            </div>
        );
    }

    if (!activeData) {
        return <div className="p-8 text-center text-text-subtle">File not found.</div>;
    }

    const {
        job_id,
        summary,
        feedbacks = [],
        file_name,
        status,
        error_message,
        empty_reason,
        raw_transcript_text,
        translated_text,
    } = activeData;
    const audioJobId = job_id || fileId;
    const failed = status === 'FAILED' || status === 'ERROR';
    const hasTranscript = Boolean(raw_transcript_text || translated_text);

    const themes: string[] = [];
    for (const item of feedbacks) {
        const name = item.tag_name || item.category_name || item.group_type;
        if (!name || themes.includes(name)) continue;
        themes.push(name);
    }

    return (
        <div className="flex h-full min-h-0 flex-col overflow-hidden bg-bg px-8 pt-8 pb-6 text-text font-sans">
            <div className="mb-4 flex shrink-0 flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
                <div>
                    <h1 className="text-2xl font-bold tracking-tight text-text">File</h1>
                    <p className="mt-1 text-sm text-text-subtle">{file_name || fileId}</p>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                        {status ? <JobStatusBadge status={status as JobStatus} /> : null}
                        <span className="text-sm text-text-subtle">
                            {feedbacks.length} insight{feedbacks.length === 1 ? '' : 's'}
                        </span>
                        <AudioPlayer jobId={audioJobId} fileName={file_name || undefined} />
                    </div>
                </div>
                <Button
                    type="button"
                    variant="secondary"
                    onClick={() => setTranscriptOpen(true)}
                    disabled={!hasTranscript}
                    className="gap-2 self-start"
                >
                    <LuExpand className="h-4 w-4" />
                    Expand
                </Button>
            </div>

            {failed && error_message ? (
                <div className="mb-4 shrink-0 rounded-lg border border-status-red-fg/30 bg-status-red px-4 py-3 text-sm text-status-red-fg">
                    <span className="font-semibold">Pipeline error: </span>
                    {error_message}
                </div>
            ) : null}

            {!failed && empty_reason && feedbacks.length === 0 ? (
                <div className="mb-4 shrink-0 rounded-lg border border-border bg-surface-raised px-4 py-3 text-sm text-text-subtle">
                    {empty_reason}
                </div>
            ) : null}

            <div className="mb-4 flex min-h-[240px] flex-1 flex-col gap-6 overflow-hidden lg:flex-row">
                <div className="h-full min-h-0 w-full flex-1 overflow-hidden overflow-y-scroll rounded-xl border border-border bg-surface app-scrollbar">
                    <table className="w-full border-collapse text-left">
                        <thead className="sticky top-0 z-10 shadow-sm">
                            <tr className="border-b border-border bg-surface-raised">
                                <th colSpan={5} className="px-4 py-3">
                                    <div className="flex items-center gap-3">
                                        <span className="text-[13px] font-semibold uppercase tracking-wide text-text">Insights</span>
                                        {summary?.summary_product ? (
                                            <span className="inline-flex items-center rounded-full border border-brand-subtle bg-brand-subtle px-3 py-1 text-[13px] font-medium text-brand">
                                                {summary.summary_product}
                                            </span>
                                        ) : null}
                                    </div>
                                </th>
                            </tr>
                            <tr className="border-b border-border bg-surface">
                                <th className="w-[14%] px-5 py-3 text-[11px] font-semibold uppercase tracking-wider text-text-subtle">Product group</th>
                                <th className="w-[16%] px-5 py-3 text-[11px] font-semibold uppercase tracking-wider text-text-subtle">Product name</th>
                                <th className="w-[16%] px-5 py-3 text-[11px] font-semibold uppercase tracking-wider text-text-subtle">Tag</th>
                                <th className="w-[27%] px-5 py-3 text-[11px] font-semibold uppercase tracking-wider text-text-subtle">Raw Verbatim</th>
                                <th className="w-[27%] px-5 py-3 text-[11px] font-semibold uppercase tracking-wider text-text-subtle">AI Summary</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-border">
                            {feedbacks.length === 0 ? (
                                <tr>
                                    <td colSpan={5} className="px-5 py-8 text-sm text-text-subtle">
                                        {empty_reason || 'No insights were generated for this file.'}
                                    </td>
                                </tr>
                            ) : feedbacks.map((item: FeedbackItem, i: number) => (
                                    <tr key={`${item.tag_name || item.category_name || 'row'}-${i}`} className="group">
                                        <td className="bg-surface-raised px-5 py-4 align-top text-sm font-medium text-text border-l-4 border-border">
                                            {item.group_type || '—'}
                                        </td>
                                        <td className="bg-surface px-5 py-4 align-top text-sm text-text">
                                            {item.product_name || '—'}
                                        </td>
                                        <td className="bg-surface px-5 py-4 align-top text-sm text-text">
                                            {item.tag_name || item.category_name || '—'}
                                        </td>
                                        <td className="bg-surface px-5 py-4 align-top text-sm text-text-subtle">
                                            {item.verbatim_quote}
                                        </td>
                                        <td className="bg-brand-subtle px-5 py-4 align-top text-sm font-medium text-brand">
                                            {item.remarks}
                                        </td>
                                    </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                <div className="flex w-full flex-col gap-5 lg:w-[320px] xl:w-[380px]">
                    <Card className="relative rounded-xl border border-border bg-surface p-6 shadow-sm">
                        <div className="mb-4 flex items-start justify-between">
                            <div>
                                <h3 className="text-[15px] font-semibold text-text">Feedback Themes</h3>
                                <p className="mt-0.5 text-xs text-text-disabled">Tags from this file</p>
                            </div>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2.5">
                            {themes.length === 0 ? (
                                <span className="text-sm text-text-subtle">No tags for this file.</span>
                            ) : themes.map((theme) => (
                                <span
                                    key={theme}
                                    className="inline-flex items-center rounded-full border border-border bg-surface-raised px-3.5 py-1.5 text-xs font-medium text-text"
                                >
                                    {theme}
                                </span>
                            ))}
                        </div>
                    </Card>
                </div>
            </div>

            <ReportModal
                open={transcriptOpen}
                title="Transcript"
                subtitle={file_name || fileId}
                wide
                onClose={() => setTranscriptOpen(false)}
            >
                <div className="grid h-[75vh] min-h-0 grid-cols-1 gap-4 md:grid-cols-2">
                    <TranscriptPane
                        title="Raw transcript"
                        text={raw_transcript_text}
                        empty="Raw STT text is not available yet."
                    />
                    <TranscriptPane
                        title="Full conversation"
                        text={translated_text}
                        empty="Translated conversation is not available yet."
                    />
                </div>
            </ReportModal>
        </div>
    );
}
