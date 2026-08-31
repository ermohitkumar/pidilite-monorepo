import {
    LuActivity,
    LuCircleCheck,
    LuCircleX,
    LuClock,
    LuTriangleAlert,
} from 'react-icons/lu';
import { Badge } from '@/components/ui/badge';
import type { BatchStatus } from '@/lib/monitor/types';

type BadgeVariant = 'brand' | 'success' | 'warning' | 'default' | 'error';

const STATUS_CONFIG: Record<
    BatchStatus,
    { label: string; variant: BadgeVariant; icon: React.ReactNode }
> = {
    PROCESSING: { label: 'PROCESSING', variant: 'brand', icon: <LuActivity className="h-3 w-3" /> },
    COMPLETED: { label: 'COMPLETED', variant: 'success', icon: <LuCircleCheck className="h-3 w-3" /> },
    PARTIAL_SUCCESS: { label: 'PARTIAL_SUCCESS', variant: 'warning', icon: <LuTriangleAlert className="h-3 w-3" /> },
    PENDING: { label: 'PENDING', variant: 'default', icon: <LuClock className="h-3 w-3" /> },
    FAILED: { label: 'FAILED', variant: 'error', icon: <LuCircleX className="h-3 w-3" /> },
};

export function BatchStatusBadge({ status }: { status: BatchStatus }) {
    const cfg = STATUS_CONFIG[status];
    return (
        <Badge variant={cfg.variant} icon={cfg.icon}>
            {cfg.label}
        </Badge>
    );
}
