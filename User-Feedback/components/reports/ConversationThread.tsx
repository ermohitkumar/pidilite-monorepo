"use client";

import { useLayoutEffect, useMemo, useRef, type ReactNode } from "react";

import {
    matchExcerptInTurns,
    parseConversationTurns,
    type ExcerptHit,
    type TextRange,
} from "@/lib/reports/conversation";

function HighlightedBody({
    text,
    ranges,
}: Readonly<{
    text: string;
    ranges: TextRange[];
}>) {
    const marks = ranges.filter((range) => range.end > range.start).sort((a, b) => a.start - b.start);
    if (marks.length === 0) {
        return <p className="whitespace-pre-wrap break-words">{text}</p>;
    }
    const parts: ReactNode[] = [];
    let cursor = 0;
    marks.forEach((range, index) => {
        const start = Math.max(range.start, cursor);
        const end = Math.max(range.end, start);
        if (start > cursor) parts.push(text.slice(cursor, start));
        if (end > start) {
            parts.push(
                <mark key={`mark-${index}-${start}`} className="rounded px-0.5 bg-amber-200 text-amber-950">
                    {text.slice(start, end)}
                </mark>,
            );
        }
        cursor = Math.max(cursor, end);
    });
    if (cursor < text.length) parts.push(text.slice(cursor));
    return <p className="whitespace-pre-wrap break-words">{parts}</p>;
}

function bubbleClass(highlighted: boolean, mine: boolean): string {
    if (highlighted) {
        return "rounded-md border-2 border-amber-400 bg-amber-50 text-amber-950";
    }
    if (mine) return "rounded-br-md bg-brand text-white";
    return "rounded-bl-md border border-slate-200 bg-white text-slate-800";
}

function labelClass(highlighted: boolean, mine: boolean): string {
    if (highlighted) return "text-amber-700";
    if (mine) return "text-right text-brand";
    return "text-slate-500";
}

export function ConversationThread({
    text,
    excerpt,
}: Readonly<{
    text: string;
    excerpt?: string | null;
    rawText?: string | null;
}>) {
    const turns = useMemo(() => parseConversationTurns(text), [text]);
    const hits = useMemo(() => matchExcerptInTurns(turns, excerpt), [turns, excerpt]);
    const hitByTurn = useMemo(() => {
        const map = new Map<number, ExcerptHit>();
        hits.forEach((hit) => map.set(hit.turnIndex, hit));
        return map;
    }, [hits]);
    const firstHit = hits[0]?.turnIndex ?? -1;
    const excerptRef = useRef<HTMLDivElement | null>(null);

    useLayoutEffect(() => {
        if (firstHit < 0) return;
        const node = excerptRef.current;
        if (!node) return;
        const timer = window.setTimeout(() => {
            node.scrollIntoView({ block: "center", behavior: "smooth" });
        }, 50);
        return () => window.clearTimeout(timer);
    }, [text, excerpt, firstHit]);

    if (turns.length === 0) {
        return (
            <pre className="whitespace-pre-wrap break-words font-sans text-base leading-7 text-slate-800">
                {text || "Full conversation is not available."}
            </pre>
        );
    }

    return (
        <div className="-mx-5 -my-4 min-h-full bg-slate-100 px-4 py-5">
            <div className="mx-auto flex max-w-2xl flex-col gap-3">
                {turns.map((turn, index) => {
                    const mine = turn.side === "right";
                    const hit = hitByTurn.get(index);
                    const highlighted = Boolean(hit);
                    let label = "";
                    if (hit?.complete) label = " · Excerpt";
                    else if (hit) label = " · Partial excerpt";
                    return (
                        <div
                            key={`${turn.speaker}-${index}`}
                            ref={index === firstHit ? excerptRef : undefined}
                            className={`flex ${mine ? "justify-end" : "justify-start"}`}
                        >
                            <div className={`flex max-w-[80%] flex-col ${mine ? "items-end" : "items-start"}`}>
                                <div className={`mb-1 px-1 text-[13px] font-semibold ${labelClass(highlighted, mine)}`}>
                                    {turn.speaker}
                                    {label}
                                </div>
                                <div className={`rounded-2xl px-3.5 py-2.5 text-base leading-7 shadow-sm ${bubbleClass(highlighted, mine)}`}>
                                    <HighlightedBody text={turn.text} ranges={hit?.ranges || []} />
                                </div>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}
