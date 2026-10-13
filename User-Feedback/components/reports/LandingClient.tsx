"use client";

import Link from "next/link";

import { useDashboardSummary } from "@/lib/hooks/queries";

const MENU_TILES = [
    { label: "Summary", href: "/reports", color: "#2f6fe0" },
    { label: "Feedback", href: "/reports/insights", color: "#7b3aed" },
    { label: "Compliance", href: "/reports/compliance", color: "#0f9aae" },
] as const;

const tileClass =
    "flex h-36 w-56 items-center justify-center rounded-md px-5 text-center text-white shadow-[0_8px_18px_rgba(16,4,36,0.12)]";

function formatCount(value: number | undefined, loading: boolean): string {
    if (loading || value === undefined || !Number.isFinite(value)) return "—";
    return value.toLocaleString();
}

export default function LandingClient() {
    const { data: summaryRes, isLoading, isError } = useDashboardSummary();
    const summary = summaryRes?.data;
    const waiting = isLoading && !summary;
    const missing = isError && !summary;

    const stats = [
        {
            label: "No. of recordings processed",
            value: formatCount(missing ? undefined : summary?.recordings_processed, waiting),
            color: "#c026d3",
        },
        {
            label: "Processed in 24 hours",
            value: formatCount(missing ? undefined : summary?.files_processed_24h?.count, waiting),
            color: "#2563eb",
        },
    ];

    return (
        <div className="flex min-h-full items-center justify-center overflow-x-hidden bg-[#c5eef8] px-8 py-12">
            <div className="flex max-w-5xl flex-col items-center gap-8">
                <nav aria-label="Home" className="flex flex-wrap items-center justify-center gap-5">
                    {MENU_TILES.map((tile) => (
                        <Link
                            key={tile.href}
                            href={tile.href}
                            className={`${tileClass} text-2xl font-semibold transition hover:brightness-110`}
                            style={{ backgroundColor: tile.color }}
                        >
                            {tile.label}
                        </Link>
                    ))}
                </nav>

                <section aria-label="Processing stats" className="flex flex-wrap items-center justify-center gap-5">
                    {stats.map((tile) => (
                        <div
                            key={tile.label}
                            className={`${tileClass} cursor-default flex-col gap-2`}
                            style={{ backgroundColor: tile.color }}
                        >
                            <p className="text-4xl font-bold leading-none tabular-nums">{tile.value}</p>
                            <p className="text-sm font-medium leading-snug">{tile.label}</p>
                        </div>
                    ))}
                </section>
            </div>
        </div>
    );
}
