"use client";

type DateRangeFilterProps = {
    startDate: string;
    endDate: string;
    onStartDateChange: (value: string) => void;
    onEndDateChange: (value: string) => void;
};

export function DateRangeFilter({
    startDate,
    endDate,
    onStartDateChange,
    onEndDateChange,
}: DateRangeFilterProps) {
    return (
        <div className="flex items-center gap-3">
            <label className="flex items-center gap-2 text-label-sm whitespace-nowrap text-text-subtle">
                Start date
                <input
                    type="date"
                    value={startDate}
                    max={endDate || undefined}
                    onChange={(event) => onStartDateChange(event.target.value)}
                    className="h-9 rounded border border-border bg-bg px-2 text-sm text-text"
                />
            </label>
            <label className="flex items-center gap-2 text-label-sm whitespace-nowrap text-text-subtle">
                End date
                <input
                    type="date"
                    value={endDate}
                    min={startDate || undefined}
                    onChange={(event) => onEndDateChange(event.target.value)}
                    className="h-9 rounded border border-border bg-bg px-2 text-sm text-text"
                />
            </label>
        </div>
    );
}
