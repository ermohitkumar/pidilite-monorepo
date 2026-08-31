import { Card } from '@/components/ui/card';

interface StatCardProps {
    label: string;
    value: string | number | null | undefined;
    sub?: string;
    icon?: React.ReactNode;
    subColor?: string;
}

export function StatCard({
    label,
    value,
    sub,
    icon,
    subColor = 'text-text-subtle',
}: StatCardProps) {
    const safeValue =
        typeof value === 'number' && !Number.isFinite(value) ? null : value;

    return (
        <Card className="flex flex-col gap-2 p-5 flex-1 min-w-0">
            <div className="flex items-center justify-between">
                <span className="text-body-sm text-text-subtle">{label}</span>
                {icon && <span className="text-text-disabled">{icon}</span>}
            </div>
            <p className="text-h2 font-bold text-text">{safeValue ?? '--'}</p>
            {sub && <p className={`text-body-sm ${subColor}`}>{sub}</p>}
        </Card>
    );
}
