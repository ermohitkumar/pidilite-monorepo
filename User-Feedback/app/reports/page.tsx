import { Suspense } from "react";

import SummariesClient from "@/components/reports/SummariesClient";

export default function ReportsPage() {
    return (
        <div className="h-full w-full">
            <Suspense fallback={<div className="p-6 text-sm text-slate-500">Loading summaries…</div>}>
                <SummariesClient />
            </Suspense>
        </div>
    );
}
