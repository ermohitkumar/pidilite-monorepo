"use client";

import { useEffect, type ReactNode } from "react";
import { LuX } from "react-icons/lu";

export function ReportModal({
    open,
    title,
    subtitle,
    headerExtra,
    onClose,
    wide,
    children,
}: Readonly<{
    open: boolean;
    title: string;
    subtitle?: string;
    headerExtra?: ReactNode;
    onClose: () => void;
    wide?: boolean;
    children: ReactNode;
}>) {
    useEffect(() => {
        if (!open) return;
        const onKey = (event: KeyboardEvent) => {
            if (event.key === "Escape") onClose();
        };
        document.addEventListener("keydown", onKey);
        document.body.style.overflow = "hidden";
        return () => {
            document.removeEventListener("keydown", onKey);
            document.body.style.overflow = "";
        };
    }, [open, onClose]);

    if (!open) return null;

    return (
        <div
            className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/40 backdrop-blur-sm p-0 sm:p-6"
            onClick={onClose}
            onKeyDown={(event) => {
                if (event.key === "Escape") onClose();
            }}
            role="presentation"
        >
            <div
                role="dialog"
                aria-modal="true"
                aria-label={title}
                className={`relative flex max-h-[92vh] w-full flex-col overflow-hidden rounded-t-2xl sm:rounded-xl border border-border bg-surface shadow-2xl ${
                    wide ? "max-w-5xl h-[92vh]" : "max-w-2xl"
                }`}
                onClick={(event) => event.stopPropagation()}
            >
                <div className="flex items-center gap-3 border-b border-border px-5 py-3 shrink-0">
                    <h2 className="shrink-0 text-lg font-semibold text-text">{title}</h2>
                    {headerExtra ? <div className="min-w-0">{headerExtra}</div> : null}
                    {subtitle ? (
                        <p className="ml-auto truncate text-sm text-text-subtle">{subtitle}</p>
                    ) : (
                        <div className="ml-auto" />
                    )}
                    <button
                        type="button"
                        onClick={onClose}
                        className="shrink-0 rounded-full p-1.5 text-text-disabled hover:bg-surface-raised hover:text-text"
                        aria-label="Close"
                    >
                        <LuX className="h-5 w-5" />
                    </button>
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
            </div>
        </div>
    );
}
