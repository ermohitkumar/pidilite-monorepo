"use client";

import { BatchStatusBadge } from '@/components/monitor/BatchStatusBadge';
import { Pagination } from '@/components/ui/Pagination';
import { ProgressBar } from '@/components/ui/ProgressBar';
import { SearchInput } from '@/components/ui/SearchInput';
import { Select } from '@/components/ui/Select';
import { StatCard } from '@/components/ui/StatCard';
import { TableEmpty, TableLoading } from '@/components/ui/TableStatus';
import { Button } from '@/components/ui/button';
import type { Batch, BatchStatus } from '@/lib/monitor/types';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import {
    LuActivity,
    LuArrowUpDown,
    LuChevronDown,
    LuChevronUp,
    LuCircleCheck,
    LuCircleX
} from 'react-icons/lu';
import { toast } from 'sonner';

import { useBatches, useDashboardSummary } from '@/lib/hooks/queries';
import { useDebouncedValue } from '@/lib/hooks/useDebouncedValue';

const FILTER_OPTIONS: Array<{ label: string; value: BatchStatus | 'ALL' }> = [
    { label: 'All Status', value: 'ALL' },
    { label: 'Processing', value: 'PROCESSING' },
    { label: 'Completed', value: 'COMPLETED' },
    { label: 'Partial Success', value: 'PARTIAL_SUCCESS' },
    { label: 'Pending', value: 'PENDING' },
    { label: 'Failed', value: 'FAILED' },
];

const PAGE_SIZE_OPTIONS = [5, 10, 20];

export default function MonitorClient() {
    type SortKey = 'batch_id' | 'status' | 'progress' | 'created_at' | 'completed_at';
    type SortDir = 'asc' | 'desc' | null;

    const [search, setSearch] = useState('');
    const [activeFilter, setActiveFilter] = useState<BatchStatus | 'ALL'>('ALL');
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize, setPageSize] = useState(10);
    const [sortKey, setSortKey] = useState<SortKey | null>(null);
    const [sortDir, setSortDir] = useState<SortDir>(null);

    const handleSort = (key: SortKey) => {
        if (sortKey !== key) {
            setSortKey(key);
            setSortDir('asc');
        } else if (sortDir === 'asc') {
            setSortDir('desc');
        } else if (sortDir === 'desc') {
            setSortKey(null);
            setSortDir(null);
        }
        setCurrentPage(1);
    };

    const SortIcon = ({ colKey }: { colKey: SortKey }) => {
        if (sortKey !== colKey) return <LuArrowUpDown className="h-3 w-3 opacity-40" />;
        if (sortDir === 'asc') return <LuChevronUp className="h-3 w-3 text-brand" />;
        return <LuChevronDown className="h-3 w-3 text-brand" />;
    };

    const debouncedSearch = useDebouncedValue(search);

    const { data: response, isLoading, isError } = useBatches({
        page: currentPage,
        size: pageSize,
        search: debouncedSearch,
        status: activeFilter,
        sort_by: sortKey || undefined,
        sort_dir: sortDir || undefined,
    });

    useEffect(() => {
        if (isError) {
            toast.error("Failed to load batches data.");
        }
    }, [isError]);

    const { data: summaryRes } = useDashboardSummary();

    const batches: Batch[] = response?.data?.items || [];

    const metadata = response?.data?.metadata || {
        total_items: 0,
        total_pages: 1,
        current_page: 1,
        page_size: pageSize
    };

    const summary = summaryRes?.data || {
        total_batches: 0,
        active_batches: { count: 0, active_jobs: 0 },
        files_processed_24h: { count: 0, success_rate: 0 },
        failed_files: { count: 0 }
    };

    const showingFrom = metadata.total_items === 0 ? 0 : (metadata.current_page - 1) * metadata.page_size + 1;
    const showingTo = metadata.total_items === 0 ? 0 : Math.min(metadata.current_page * metadata.page_size, metadata.total_items);

    const [isMounted, setIsMounted] = useState(false);
    useEffect(() => setIsMounted(true), []);

    const formatDate = (dateStr: string | null) => {
        if (!isMounted) return '--';
        if (!dateStr) return '--';
        try {
            return new Date(dateStr).toLocaleString();
        } catch {
            return dateStr;
        }
    };
    const formatTime = (dateStr: string | null) => {
        if (!isMounted) return '--';
        if (!dateStr) return '--';
        const date = new Date(dateStr);
        return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }

    return (
        <div className="flex h-full flex-col gap-6 p-8 bg-bg">
            <div>
                <div className="flex items-center gap-3">
                    <h1 className="text-h1 font-bold text-text">Job Monitoring Dashboard</h1>
                    {/* {isFetching && !isLoading && (
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-subtle px-2.5 py-0.5 text-label-sm font-medium text-brand animate-pulse">
                            <LuActivity className="h-3 w-3" />
                            Syncing
                        </span>
                    )} */}
                </div>
                <p className="mt-1 text-body-md text-text-subtle">
                    Real-time status of the speech-to-metadata pipeline.
                </p>
            </div>

            <div className="flex gap-4">
                <StatCard
                    label="Total Batches"
                    value={summary.total_batches}
                    sub="Total batches processed"
                    icon={<LuActivity className="h-5 w-5 text-purple-500" />}
                />
                <StatCard
                    label="Active Batches"
                    value={summary.active_batches.count}
                    sub={`${summary.active_batches.active_jobs} active jobs`}
                    icon={<LuActivity className="h-5 w-5 text-gold-dark" />}
                />
                <StatCard
                    label="Files Processed (24h)"
                    value={summary.files_processed_24h.count}
                    sub={`${summary.files_processed_24h.success_rate}% success rate`}
                    icon={<LuCircleCheck className="h-5 w-5 text-status-green-fg" />}
                />
                <StatCard
                    label="Failed Files"
                    value={summary.failed_files.count}
                    sub="Requires attention"
                    icon={<LuCircleX className="h-5 w-5 text-status-red-fg" />}
                />
            </div>

            <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-surface overflow-hidden">
                <div className="flex items-center justify-between gap-4 border-b border-border px-5 py-3">
                    <SearchInput
                        value={search}
                        placeholder="Search batches..."
                        onChange={(v) => { setSearch(v); setCurrentPage(1); }}
                    />

                    <div className="w-48">
                        <Select
                            value={activeFilter}
                            onChange={(v) => {
                                setActiveFilter(v as BatchStatus | 'ALL');
                                setCurrentPage(1);
                            }}
                            options={FILTER_OPTIONS}
                            placeholder='All Status'
                        />
                    </div>
                </div>

                <div className="app-scrollbar min-h-0 flex-1 overflow-auto">
                    <table className="w-full min-w-[860px]">
                        <thead className="sticky top-0 z-10">
                            <tr className="border-b border-border bg-bg">
                                {([
                                    { label: 'BATCH ID', key: 'batch_id' as SortKey },
                                    { label: 'STATUS' },
                                    { label: 'PROGRESS' },
                                    { label: 'START TIME' },
                                    { label: 'END TIME' },
                                    { label: 'CREATED', key: 'created_at' as SortKey },
                                    { label: 'ACTIONS', key: null },
                                ] as Array<{ label: string; key?: SortKey | null }>).map(({ label, key }) =>
                                    key ? (
                                        <th
                                            key={label}
                                            onClick={() => handleSort(key)}
                                            className="px-5 py-3 text-left text-label-sm text-text-disabled tracking-widest cursor-pointer select-none group"
                                        >
                                            <span className="inline-flex items-center gap-1.5 hover:text-text transition-colors">
                                                {label}
                                                <SortIcon colKey={key} />
                                            </span>
                                        </th>
                                    ) : (
                                        <th key={label} className="px-5 py-3 text-left text-label-sm text-text-disabled tracking-widest">
                                            {label}
                                        </th>
                                    )
                                )}
                            </tr>
                        </thead>
                        <tbody>
                            {isLoading ? (
                                <TableLoading colSpan={7} />
                            ) : batches.length === 0 ? (
                                <TableEmpty colSpan={7} message="No batches match your search." />
                            ) : (
                                batches.map((batch: Batch, idx: number) => (
                                    <tr
                                        key={batch.batch_id}
                                        className={`border-b border-border transition-colors hover:bg-surface-raised ${idx % 2 === 0 ? '' : 'bg-bg/40'
                                            }`}
                                    >
                                        <td className="px-5 py-4">
                                            <Link
                                                href={`/monitor/batches/${batch.batch_id}`}
                                                className="text-body-sm font-mono font-semibold text-brand hover:underline underline-offset-2"
                                            >
                                                {batch.batch_id}
                                            </Link>
                                        </td>
                                        <td className="px-5 py-4">
                                            <BatchStatusBadge status={batch.status} />
                                        </td>
                                        <td className="px-5 py-4">
                                            <ProgressBar processed={batch.completed_jobs} total={batch.total_jobs} />
                                        </td>
                                        <td className="px-5 py-4 text-body-sm font-mono text-text-subtle">{formatTime(batch.created_at)}</td>
                                        <td className="px-5 py-4 text-body-sm font-mono text-text-subtle">{formatTime(batch.completed_at)}</td>
                                        <td className="px-5 py-4 text-body-sm font-mono text-text-subtle">{formatDate(batch.created_at)}</td>
                                        <td className="px-5 py-4">
                                            <Link href={`/monitor/batches/${batch.batch_id}`}>
                                                <Button variant="action">
                                                    View
                                                </Button>
                                            </Link>
                                        </td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>

                <Pagination
                    currentPage={metadata.current_page}
                    totalPages={metadata.total_pages}
                    pageSize={metadata.page_size}
                    pageSizeOptions={PAGE_SIZE_OPTIONS}
                    totalItems={metadata.total_items}
                    showingFrom={showingFrom}
                    showingTo={showingTo}
                    itemLabel="batches"
                    selectId="batch-page-size"
                    onPageChange={setCurrentPage}
                    onPageSizeChange={(size) => { setPageSize(size); setCurrentPage(1); }}
                />
            </div>
        </div >
    );
}
