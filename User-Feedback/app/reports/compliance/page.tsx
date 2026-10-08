import { Suspense } from "react";

import ComplianceClient from "@/components/reports/ComplianceClient";

export default function CompliancePage() {
    return (
        <div className="h-full w-full">
            <Suspense fallback={<div className="p-6 text-sm text-slate-500">Loading compliance…</div>}>
                <ComplianceClient />
            </Suspense>
        </div>
    );
}
