"use client";

import { useMemo, useState } from "react";
import { LuMessageSquare, LuQuote, LuSparkles } from "react-icons/lu";

import { ConversationThread } from "@/components/reports/ConversationThread";
import { FileSourceLink } from "@/components/reports/FileSourceLink";
import { ReportModal } from "@/components/reports/ReportModal";
import {
    buildBreakdown,
    drillPath,
    drillTitle,
    factMatchingDrill,
    uniqueFeedbackItems,
} from "@/lib/reports/build";
import { isFullConversationTitle } from "@/lib/reports/conversation";
import type { DrillScope, FeedbackFactRow } from "@/lib/reports/types";

function CountButton({
    count,
    onClick,
}: Readonly<{ count: number; onClick: () => void }>) {
    if (!count) return <span className="text-slate-400">0</span>;
    return (
        <button
            type="button"
            onClick={onClick}
            className="inline-flex min-w-8 items-center justify-center rounded-full bg-brand-subtle px-2.5 py-0.5 text-sm font-semibold text-brand hover:bg-brand hover:text-white transition-colors"
        >
            {count}
        </button>
    );
}

export function DrillDownModal({
    open,
    fact,
    drill,
    onClose,
    onDrill,
    onBack,
}: Readonly<{
    open: boolean;
    fact: FeedbackFactRow[];
    drill: DrillScope | null;
    onClose: () => void;
    onDrill: (next: DrillScope) => void;
    onBack?: () => void;
}>) {
    const [textModal, setTextModal] = useState<{
        title: string;
        body: string;
        excerpt?: string;
    } | null>(null);

    const isConversation = isFullConversationTitle(textModal?.title);

    const scoped = useMemo(
        () => (drill ? factMatchingDrill(fact, drill) : []),
        [fact, drill],
    );
    const breakdown = useMemo(
        () => (drill ? buildBreakdown(fact, drill) : []),
        [fact, drill],
    );
    const items = useMemo(() => uniqueFeedbackItems(scoped), [scoped]);
    const showBreakdown = Boolean(drill && breakdown.length > 0 && drill.level !== "item");

    if (!drill) return null;

    return (
        <>
            <ReportModal
                open={open}
                wide
                title={drillTitle(drill)}
                subtitle={`${drillPath(drill).join(" → ")} · ${items.length} feedback${items.length === 1 ? "" : "s"}`}
                onClose={onClose}
            >
                {onBack ? (
                    <button
                        type="button"
                        onClick={onBack}
                        className="mb-4 text-sm font-medium text-brand hover:underline"
                    >
                        ← Back
                    </button>
                ) : null}
                {showBreakdown ? (
                    <div className="mb-6">
                        <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">
                            Breakdown — click a count to go deeper
                        </h3>
                        <div className="overflow-hidden rounded-lg border border-border">
                            <table className="w-full text-sm">
                                <thead className="bg-[#FFC000] text-left">
                                    <tr>
                                        <th className="px-3 py-2 font-bold">Level</th>
                                        <th className="px-3 py-2 font-bold text-center w-28">Count</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {breakdown.map((row) => (
                                        <tr key={row.label} className="border-t border-border hover:bg-slate-50">
                                            <td className="px-3 py-2">{row.label}</td>
                                            <td className="px-3 py-2 text-center">
                                                <CountButton count={row.count} onClick={() => onDrill(row.drill)} />
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </div>
                ) : null}

                <h3 className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">
                    Feedback behind this count
                </h3>
                {items.length === 0 ? (
                    <p className="text-sm text-slate-500">No feedback rows at this level.</p>
                ) : (
                    <div className="space-y-3">
                        {items.map((item, index) => (
                            <article
                                key={item.feedback_id || `${item.job_id}-${index}`}
                                className="rounded-lg border border-border bg-bg p-4"
                            >
                                <div className="flex flex-wrap gap-2 mb-3 text-xs">
                                    {item.product_name ? (
                                        <span className="rounded-full bg-slate-100 px-2 py-0.5 text-slate-700">
                                            {item.product_name}
                                        </span>
                                    ) : null}
                                    {item.feedback_category ? (
                                        <span className="rounded-full bg-brand-subtle px-2 py-0.5 text-brand">
                                            {item.feedback_category}
                                        </span>
                                    ) : null}
                                    {item.feedback_tag ? (
                                        <span className="rounded-full bg-amber-50 px-2 py-0.5 text-amber-800">
                                            {item.feedback_tag}
                                        </span>
                                    ) : null}
                                </div>
                                <p className="whitespace-pre-wrap text-sm text-slate-800">
                                    {item.feedback_summary_ai || item.feedback_excerpt || "No summary available."}
                                </p>
                                <div className="mt-3 flex flex-wrap gap-2">
                                    {item.job_id ? (
                                        <FileSourceLink
                                            jobId={item.job_id}
                                            fileName={item.file_name || "Open source file"}
                                            className="inline-flex items-center rounded-md border border-border bg-white px-2.5 py-1 text-xs font-medium text-brand hover:bg-slate-50"
                                        />
                                    ) : null}
                                    <button
                                        type="button"
                                        className="inline-flex items-center gap-1.5 rounded-md border border-border bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
                                        onClick={() =>
                                            setTextModal({
                                                title: "AI summary",
                                                body: item.feedback_summary_ai || "No AI summary for this feedback.",
                                            })
                                        }
                                    >
                                        <LuSparkles className="h-3.5 w-3.5" />
                                        Summary
                                    </button>
                                    <button
                                        type="button"
                                        className="inline-flex items-center gap-1.5 rounded-md border border-border bg-white px-2.5 py-1 text-xs font-medium text-blue-700 hover:bg-blue-50"
                                        onClick={() =>
                                            setTextModal({
                                                title: "Voice excerpt",
                                                body: item.feedback_excerpt || "No excerpt for this feedback.",
                                            })
                                        }
                                    >
                                        <LuQuote className="h-3.5 w-3.5" />
                                        Excerpt
                                    </button>
                                    <button
                                        type="button"
                                        className="inline-flex items-center gap-1.5 rounded-md border border-brand bg-brand px-2.5 py-1 text-xs font-medium text-white hover:bg-brand-dark"
                                        onClick={() =>
                                            setTextModal({
                                                title: "Full conversation",
                                                body: item.full_conversation || "Full conversation is not available for this row.",
                                                excerpt: item.feedback_excerpt || undefined,
                                            })
                                        }
                                    >
                                        <LuMessageSquare className="h-3.5 w-3.5" />
                                        Full conversation
                                    </button>
                                </div>
                            </article>
                        ))}
                    </div>
                )}
            </ReportModal>

            <ReportModal
                open={Boolean(textModal)}
                wide={isConversation}
                title={textModal?.title || ""}
                onClose={() => setTextModal(null)}
            >
                {isConversation ? (
                    <ConversationThread
                        text={textModal?.body || ""}
                        excerpt={textModal?.excerpt}
                    />
                ) : (
                    <p className="whitespace-pre-wrap text-sm leading-6 text-slate-800">
                        {textModal?.body}
                    </p>
                )}
            </ReportModal>
        </>
    );
}
