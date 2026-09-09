export type PeriodKind = "month" | "quarter" | "year";

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
    if (kind === "quarter") {
        return { kind, year: currentYearValue(now), quarter: currentQuarterValue(now) };
    }
    if (kind === "year") return { kind, year: currentYearValue(now) };
    return { kind: "month", month: currentMonthValue(now) };
}
