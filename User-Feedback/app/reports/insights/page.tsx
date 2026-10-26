import { redirect } from "next/navigation";

export default async function LegacyInsightsPage({
    searchParams,
}: {
    searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
    const params = await searchParams;
    const qs = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
        if (typeof value === "string") qs.set(key, value);
        else if (Array.isArray(value)) value.forEach((item) => qs.append(key, item));
    }
    const query = qs.toString();
    redirect(query ? `/reports/feedback?${query}` : "/reports/feedback");
}
