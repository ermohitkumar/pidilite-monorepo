import { LuActivity, LuCircleCheck, LuCircleX, LuClock } from 'react-icons/lu';
import { Badge } from '@/components/ui/badge';
import type { JobStatus } from '@/lib/monitor/types';

type BadgeVariant = 'brand' | 'success' | 'warning' | 'default' | 'error';

const STATUS_CONFIG: Record<
    JobStatus,
    { label: string; variant: BadgeVariant; icon: React.ReactNode }
> = {
    PROCESSING: { label: 'PROCESSING', variant: 'brand', icon: <LuActivity className="h-3 w-3" /> },
    COMPLETED: { label: 'COMPLETED', variant: 'success', icon: <LuCircleCheck className="h-3 w-3" /> },
    FAILED: { label: 'FAILED', variant: 'error', icon: <LuCircleX className="h-3 w-3" /> },
    PENDING: { label: 'PENDING', variant: 'default', icon: <LuClock className="h-3 w-3" /> },
    BATCHED: { label: 'BATCHED', variant: 'default', icon: <LuClock className="h-3 w-3" /> },
    STT_SUBMITTED: { label: 'STT_SUBMITTED', variant: 'warning', icon: <LuActivity className="h-3 w-3" /> },
    STT_COMPLETED: { label: 'STT_COMPLETED', variant: 'warning', icon: <LuActivity className="h-3 w-3" /> },
    ERROR: { label: 'ERROR', variant: 'error', icon: <LuCircleX className="h-3 w-3" /> },
};

export function JobStatusBadge({ status }: { status: JobStatus | string }) {
    const cfg = STATUS_CONFIG[status as JobStatus] || {
        label: status || 'UNKNOWN',
        variant: 'default' as const,
        icon: <LuClock className="h-3 w-3" />,
    };
    return (
        <Badge variant={cfg.variant} icon={cfg.icon}>
            {cfg.label}
        </Badge>
    );
}
