export function ProgressBar({
    processed,
    total,
}: {
    processed: number;
    total: number;
}) {
    const pct = total === 0 ? 0 : Math.round((processed / total) * 100);
    return (
        <div className="flex items-center gap-3 min-w-[140px]">
            <div className="relative h-1.5 flex-1 rounded-full bg-surface-raised overflow-hidden">
                <div
                    className="absolute inset-y-0 left-0 rounded-full bg-brand transition-all duration-500"
                    style={{ width: `${pct}%` }}
                />
            </div>
            <span className="text-body-sm font-mono text-text-subtle whitespace-nowrap">
                {processed}/{total}
            </span>
        </div>
    );
}
