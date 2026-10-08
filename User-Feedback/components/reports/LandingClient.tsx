"use client";

import Link from "next/link";

import { complianceHref, insightsHref, summariesHref } from "@/lib/reports/period";
import { GROUP_TABS } from "@/lib/reports/types";

type IndexChild = { label: string; href: string; loc: string };
type IndexSection = { parent: string; children: IndexChild[] };

const INDEX: IndexSection[] = [
    {
        parent: "Summaries",
        children: GROUP_TABS.map((tab) => ({
            label: `${tab.label} Summaries`,
            href: summariesHref({ feedback_group: tab.id }),
            loc: "Summaries",
        })),
    },
    {
        parent: "Feedbacks",
        children: GROUP_TABS.map((tab) => ({
            label: `${tab.label} Feedbacks`,
            href: insightsHref({ feedback_group: tab.id }),
            loc: "Insights",
        })),
    },
    {
        parent: "Compliance",
        children: [{ label: "Open Conversations", href: complianceHref(), loc: "Compliance" }],
    },
];

function IndexEntry({
    label,
    href,
    loc,
    nested = false,
}: {
    label: string;
    href?: string;
    loc?: string;
    nested?: boolean;
}) {
    const rowClass = [
        "group flex w-full items-baseline gap-2 py-1.5 text-[15px] leading-snug",
        nested ? "pl-6 sm:pl-8" : "font-semibold text-slate-900",
        href ? "text-slate-800 hover:text-brand" : "",
    ]
        .filter(Boolean)
        .join(" ");

    const body = (
        <>
            <span className={nested ? "font-normal" : undefined}>{label}</span>
            <span
                aria-hidden
                className="min-w-4 flex-1 border-b border-dotted border-slate-300 group-hover:border-brand/40"
            />
            {loc ? (
                <span className="shrink-0 tabular-nums text-sm text-slate-500 group-hover:text-brand">
                    {loc}
                </span>
            ) : null}
        </>
    );

    if (href) {
        return (
            <Link href={href} className={rowClass}>
                {body}
            </Link>
        );
    }

    return <div className={rowClass}>{body}</div>;
}

export default function LandingClient() {
    return (
        <div className="mx-auto max-w-3xl p-6 sm:p-8">
            <header className="mb-8 border-b border-slate-200 pb-4 text-center">
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-slate-400">
                    User Feedback
                </p>
                <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-900">Index</h1>
            </header>

            <nav aria-label="Report index" className="columns-1 gap-x-12 sm:columns-2">
                {INDEX.map((section) => (
                    <section key={section.parent} className="mb-6 break-inside-avoid">
                        <IndexEntry label={section.parent} />
                        <ul>
                            {section.children.map((child) => (
                                <li key={child.href}>
                                    <IndexEntry
                                        label={child.label}
                                        href={child.href}
                                        loc={child.loc}
                                        nested
                                    />
                                </li>
                            ))}
                        </ul>
                    </section>
                ))}
            </nav>
        </div>
    );
}
