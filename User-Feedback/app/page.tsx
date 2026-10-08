import { Suspense } from "react";
import { redirect } from "next/navigation";

import LandingClient from "@/components/reports/LandingClient";
import { getSession } from "@/lib/auth/session";

export default async function HomePage() {
    const session = await getSession();
    if (!session) {
        redirect("/login");
    }

    return (
        <Suspense fallback={<div className="p-6 text-sm text-slate-500">Loading home…</div>}>
            <LandingClient />
        </Suspense>
    );
}
