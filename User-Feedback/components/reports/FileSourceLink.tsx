"use client";

import Link from "next/link";

export function FileSourceLink({
    jobId,
    fileName,
    className = "break-all font-medium text-brand hover:underline",
}: Readonly<{
    jobId?: string | null;
    fileName?: string | null;
    className?: string;
}>) {
    const label = fileName || "Open file";
    if (!jobId) {
        return (
            <span className="break-all text-slate-700" title={label}>
                {label}
            </span>
        );
    }
    return (
        <Link href={`/files/${jobId}`} className={className} title="Open source file">
            {fileName ? label : "Open source file"}
        </Link>
    );
}
