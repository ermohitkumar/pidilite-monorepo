import type { FeedbackGroup, ReportFilters } from "@/lib/reports/types";

export type PeriodKind = "all" | "month" | "quarter" | "year";
export type PipelinePeriodKind = "week" | "month" | "year";
export type GroupFilter = FeedbackGroup | "ALL";

export type PipelinePeriodState = {
    kind: PipelinePeriodKind;
    week?: string;
    month?: string;
    year?: string;
};

const GROUP_FROM_TOKEN: Record<string, FeedbackGroup> = {
    PDT: "PDT GROUP",
    USER: "USER GROUP",
    DEALER: "DEALER GROUP",
};

export type PeriodState = {
    kind: PeriodKind;
    month?: string;
    quarter?: string;
    year?: string;
};

function pad(value: number): string {
    return String(value).padStart(2, "0");
}

export function isoDate(date: Date): string {
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
}

export function currentMonthValue(now = new Date()): string {
    return `${now.getFullYear()}-${pad(now.getMonth() + 1)}`;
}

export function currentYearValue(now = new Date()): string {
    return String(now.getFullYear());
}

export function currentQuarterValue(now = new Date()): string {
    return String(Math.floor(now.getMonth() / 3) + 1);
}

function lastDayOfMonth(year: number, monthIndex: number): Date {
    return new Date(year, monthIndex + 1, 0);
}

export function datesForPeriod(period: PeriodState, now = new Date()): { start_date?: string; end_date?: string } {
    if (period.kind === "all") return {};
    if (period.kind === "month") {
        const value = period.month || currentMonthValue(now);
        const [yearText, monthText] = value.split("-");
        const year = Number(yearText);
        const monthIndex = Number(monthText) - 1;
        if (!Number.isFinite(year) || monthIndex < 0 || monthIndex > 11) return {};
        return {
            start_date: isoDate(new Date(year, monthIndex, 1)),
            end_date: isoDate(lastDayOfMonth(year, monthIndex)),
        };
    }

    const year = Number(period.year || currentYearValue(now));
    if (!Number.isFinite(year)) return {};

    if (period.kind === "year") {
        return { start_date: `${year}-01-01`, end_date: `${year}-12-31` };
    }

    const quarter = Number(period.quarter || currentQuarterValue(now));
    if (quarter < 1 || quarter > 4) return {};
    const startMonth = (quarter - 1) * 3;
    return {
        start_date: isoDate(new Date(year, startMonth, 1)),
        end_date: isoDate(lastDayOfMonth(year, startMonth + 2)),
    };
}

export function defaultPeriod(kind: PeriodKind, now = new Date()): PeriodState {
    if (kind === "all") return { kind: "all" };
    if (kind === "quarter") {
        return { kind, year: currentYearValue(now), quarter: currentQuarterValue(now) };
    }
    if (kind === "year") return { kind, year: currentYearValue(now) };
    return { kind: "month", month: currentMonthValue(now) };
}

/** Monday of the ISO week that contains `date` (local calendar). */
function mondayOfIsoWeek(date: Date): Date {
    const day = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    const weekday = (day.getDay() + 6) % 7; // Mon=0 … Sun=6
    day.setDate(day.getDate() - weekday);
    return day;
}

export function currentWeekValue(now = new Date()): string {
    const monday = mondayOfIsoWeek(now);
    // ISO week-year can differ from calendar year near Jan 1.
    const thursday = new Date(monday);
    thursday.setDate(monday.getDate() + 3);
    const yearStart = new Date(thursday.getFullYear(), 0, 1);
    const week =
        Math.floor(
            (Date.UTC(thursday.getFullYear(), thursday.getMonth(), thursday.getDate()) -
                Date.UTC(yearStart.getFullYear(), 0, 1)) /
                86_400_000 /
                7,
        ) + 1;
    return `${thursday.getFullYear()}-W${pad(week)}`;
}

export function datesForIsoWeek(weekValue: string): { start_date?: string; end_date?: string } {
    const match = /^(\d{4})-W(\d{2})$/.exec(weekValue.trim());
    if (!match) return {};
    const year = Number(match[1]);
    const week = Number(match[2]);
    if (!Number.isFinite(year) || week < 1 || week > 53) return {};
    // ISO week 1 is the week with the year's first Thursday.
    const jan4 = new Date(year, 0, 4);
    const monday = mondayOfIsoWeek(jan4);
    monday.setDate(monday.getDate() + (week - 1) * 7);
    const sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);
    return { start_date: isoDate(monday), end_date: isoDate(sunday) };
}

export function defaultPipelinePeriod(kind: PipelinePeriodKind = "month", now = new Date()): PipelinePeriodState {
    if (kind === "week") return { kind: "week", week: currentWeekValue(now) };
    if (kind === "year") return { kind: "year", year: currentYearValue(now) };
    return { kind: "month", month: currentMonthValue(now) };
}

export function datesForPipelinePeriod(
    period: PipelinePeriodState,
    now = new Date(),
): { start_date?: string; end_date?: string } {
    if (period.kind === "week") {
        return datesForIsoWeek(period.week || currentWeekValue(now));
    }
    return datesForPeriod(
        period.kind === "year"
            ? { kind: "year", year: period.year || currentYearValue(now) }
            : { kind: "month", month: period.month || currentMonthValue(now) },
        now,
    );
}

/** Chart grain: daily within a week/month, monthly within a year. */
export function grainForPipelinePeriod(kind: PipelinePeriodKind): "day" | "week" | "month" {
    if (kind === "year") return "month";
    return "day";
}

export function restrictToAvailable(live: string[], allowed?: string[]): string[] {
    // Empty allowed (month with no stored summaries) must not hide every dropdown.
    if (!allowed || allowed.length === 0) return live;
    const set = new Set(allowed.map((value) => value.trim().toLowerCase()));
    const filtered = live.filter((value) => set.has(value.trim().toLowerCase()));
    // Hierarchy master labels (dimhierarchy) can differ from period-summary /
    // file_details labels. An empty intersection used to blank Division/Zone/
    // RFMM/BDE while Product and User type still rendered.
    if (filtered.length > 0) return filtered;
    return allowed;
}

export function groupFromGrainKey(grainKey?: string | null): FeedbackGroup | null {
    const parts = (grainKey || "").split("::");
    if (parts.length >= 2 && GROUP_FROM_TOKEN[parts[1]]) return GROUP_FROM_TOKEN[parts[1]];
    return null;
}

export function filtersToSearchParams(filters: ReportFilters): string {
    const params = new URLSearchParams();
    (Object.entries(filters) as [keyof ReportFilters, unknown][]).forEach(([key, value]) => {
        if (value === undefined || value === null || value === "" || value === "ALL") return;
        if (Array.isArray(value)) {
            value.forEach((item) => params.append(String(key), String(item)));
            return;
        }
        params.set(String(key), String(value));
    });
    return params.toString();
}

const MULTI_FILTER_KEYS = ["division", "zone", "cluster"] as const;

export function filtersFromSearchParams(params: {
    get: (key: string) => string | null;
    getAll: (key: string) => string[];
}): ReportFilters {
    const filters: ReportFilters = {};
    MULTI_FILTER_KEYS.forEach((key) => {
        const values = params.getAll(key).map((value) => value.trim()).filter(Boolean);
        if (values.length) filters[key] = Array.from(new Set(values));
    });
    const keys: (keyof ReportFilters)[] = [
        "feedback_group",
        "feedback_category",
        "feedback_tag",
        "feedback_sub_tag",
        "product_name",
        "fme_code",
        "user_type",
        "start_date",
        "end_date",
        "search",
    ];
    keys.forEach((key) => {
        const value = params.get(key);
        if (value) (filters as Record<string, string>)[key] = value;
    });
    return filters;
}

export function periodFromDateRange(start?: string, end?: string, now = new Date()): PeriodState {
    if (!start || !end) return defaultPeriod("all", now);
    const startDate = new Date(`${start}T00:00:00`);
    const endDate = new Date(`${end}T00:00:00`);
    if (Number.isNaN(startDate.getTime()) || Number.isNaN(endDate.getTime())) return defaultPeriod("all", now);
    if (
        startDate.getMonth() === 0 &&
        startDate.getDate() === 1 &&
        endDate.getMonth() === 11 &&
        endDate.getDate() === 31 &&
        startDate.getFullYear() === endDate.getFullYear()
    ) {
        return { kind: "year", year: String(startDate.getFullYear()) };
    }
    const quarter = Math.floor(startDate.getMonth() / 3) + 1;
    const qStart = new Date(startDate.getFullYear(), (quarter - 1) * 3, 1);
    const qEnd = lastDayOfMonth(startDate.getFullYear(), (quarter - 1) * 3 + 2);
    if (isoDate(startDate) === isoDate(qStart) && isoDate(endDate) === isoDate(qEnd)) {
        return { kind: "quarter", year: String(startDate.getFullYear()), quarter: String(quarter) };
    }
    return {
        kind: "month",
        month: `${startDate.getFullYear()}-${pad(startDate.getMonth() + 1)}`,
    };
}

export function insightsHref(filters: ReportFilters): string {
    const qs = filtersToSearchParams(filters);
    return qs ? `/reports/feedback?${qs}` : "/reports/feedback";
}

export function summariesHref(filters: ReportFilters): string {
    const qs = filtersToSearchParams(filters);
    return qs ? `/reports?${qs}` : "/reports";
}

export function complianceHref(filters: ReportFilters = {}): string {
    const qs = filtersToSearchParams(filters);
    return qs ? `/reports/compliance?${qs}` : "/reports/compliance";
}

export function hasVisibleSummary(record?: { status?: string; summary_text?: string | null } | null): boolean {
    if (!record || record.status !== "ok") return false;
    const text = (record.summary_text || "").trim();
    if (!text) return false;
    return !text.toLowerCase().startsWith("no insights");
}
