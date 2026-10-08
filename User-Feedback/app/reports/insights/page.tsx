import { Suspense } from "react";

import ReportsClient from "@/components/reports/ReportsClient";

export default function ReportInsightsPage() {
    return (
        <div className="h-full w-full">
            <Suspense fallback={<div className="p-6 text-sm text-slate-500">Loading insights…</div>}>
                <ReportsClient />
            </Suspense>
        </div>
    );
}
