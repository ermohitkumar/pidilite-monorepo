"use client";

import { JobStatusBadge } from '@/components/monitor/JobStatusBadge';
import { Pagination } from '@/components/ui/Pagination';
import { SearchInput } from '@/components/ui/SearchInput';
import { StatCard } from '@/components/ui/StatCard';
import { Button } from '@/components/ui/button';
import { TableEmpty, TableLoading } from '@/components/ui/TableStatus';
import { PageLoader } from '@/components/ui/PageLoader';
import { useBatchDetails } from '@/lib/hooks/queries';
import { useDebouncedValue } from '@/lib/hooks/useDebouncedValue';
import type { Job, JobStatus, PaginationMeta } from '@/lib/monitor/types';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { LuActivity, LuArrowLeft, LuArrowUpDown, LuChevronDown, LuChevronUp, LuFilter, LuCircleCheck, LuCircleX, LuClock } from 'react-icons/lu';
import { toast } from 'sonner';

const PAGE_SIZE_OPTIONS = [5, 10, 20, 50];

const FILTER_OPTIONS: Array<{ label: string; value: JobStatus | 'ALL' }> = [
    { label: 'All', value: 'ALL' },
    { label: 'Pending', value: 'PENDING' },
    { label: 'Batched', value: 'BATCHED' },
    { label: 'STT Submitted', value: 'STT_SUBMITTED' },
    { label: 'STT Completed', value: 'STT_COMPLETED' },
    { label: 'Processing', value: 'PROCESSING' },
    { label: 'Completed', value: 'COMPLETED' },
    { label: 'Failed', value: 'FAILED' },
    { label: 'Error', value: 'ERROR' }
];

type BatchDetailClientProps = {
    batchId: string;
    batch?: any;
    batchFiles?: Job[];
};

export default function BatchDetailClient({ batchId }: BatchDetailClientProps) {
    type SortKey = 'job_id' | 'file_name' | 'created_at';
    type SortDir = 'asc' | 'desc' | null;

    const [search, setSearch] = useState('');
    const [filterOpen, setFilterOpen] = useState(false);
    const [activeFilter, setActiveFilter] = useState<JobStatus | 'ALL'>('ALL');
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize, setPageSize] = useState(10);
    const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
    const [sortKey, setSortKey] = useState<SortKey | null>(null);
    const [sortDir, setSortDir] = useState<SortDir>(null);

    const handleSort = (key: SortKey) => {
        if (sortKey !== key) { setSortKey(key); setSortDir('asc'); }
        else if (sortDir === 'asc') { setSortDir('desc'); }
        else { setSortKey(null); setSortDir(null); }
        setCurrentPage(1);
    };

    const SortIcon = ({ colKey }: { colKey: SortKey }) => {
        if (sortKey !== colKey) return <LuArrowUpDown className="h-3 w-3 opacity-40" />;
        if (sortDir === 'asc') return <LuChevronUp className="h-3 w-3 text-brand" />;
        return <LuChevronDown className="h-3 w-3 text-brand" />;
    };

    const debouncedSearch = useDebouncedValue(search);

    const { data: response, isLoading, isError } = useBatchDetails(batchId, {
        page: currentPage,
        size: pageSize,
        search: debouncedSearch,
        status: activeFilter,
        sort_by: sortKey || undefined,
        sort_dir: sortDir || undefined,
    });

    useEffect(() => {
        if (isError) {
            toast.error("Failed to load batch details.");
        }
    }, [isError]);

    const batch_info = response?.data?.batch_info;

    const jobs: Job[] = response?.data?.jobs?.items || [];

    const metadata: PaginationMeta = {
        total_items: response?.data?.jobs?.metadata?.total_items || 0,
        total_pages: response?.data?.jobs?.metadata?.total_pages || 1,
        current_page: response?.data?.jobs?.metadata?.current_page || 1,
        page_size: response?.data?.jobs?.metadata?.page_size || pageSize,
        has_next: response?.data?.jobs?.metadata?.has_next || false,
        has_previous: response?.data?.jobs?.metadata?.has_previous || false,
        completed_jobs: response?.data?.jobs?.metadata?.completed_jobs || 0,
        failed_jobs: response?.data?.jobs?.metadata?.failed_jobs || 0
    }

    const [isMounted, setIsMounted] = useState(false);
    useEffect(() => setIsMounted(true), []);

    if (isLoading && !batch_info) {
        return <PageLoader text="Loading batch details..." />;
    }

    if (!batch_info) {
        return <div className="p-8 text-status-red-fg text-body-md text-center py-20">Batch not found</div>;
    }

    const showingFrom = metadata.total_items === 0 ? 0 : (metadata.current_page - 1) * metadata.page_size + 1;
    const showingTo = metadata.total_items === 0 ? 0 : Math.min(metadata.current_page * metadata.page_size, metadata.total_items);

    function toggleRow(id: string) {
        setSelectedIds((prev) => {
            const next = new Set(prev);
            next.has(id) ? next.delete(id) : next.add(id);
            return next;
        });
    }

    const formatDate = (dateStr: string | null) => {
        if (!isMounted) return '--';
        if (!dateStr) return '--';
        try {
            return new Date(dateStr).toLocaleString();
        } catch {
            return dateStr;
        }
    };

    const extraInfo = `${metadata.completed_jobs} completed · ${metadata.failed_jobs} failed`;

    return (
        <div className="flex flex-col gap-6 p-8 min-h-screen bg-bg">

            {/* Breadcrumb + back button */}
            <div className="flex justify-between items-center">
                <div className="flex items-center gap-4">
                    <div className="flex items-center gap-2 text-body-lg">
                        <Link href="/monitor" className="text-text-subtle hover:text-brand transition-colors font-semibold">
                            Batches
                        </Link>
                        <span className="text-text-disabled">/</span>
                        <span className="text-brand font-semibold">{batch_info.batch_id}</span>
                    </div>
                    {/* {isFetching && !isLoading && (
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-subtle px-2.5 py-0.5 text-label-sm font-medium text-brand animate-pulse">
                            <LuActivity className="h-3 w-3" />
                            Syncing
                        </span>
                    )} */}
                </div>
                <Button
                    onClick={() => window.history.back()}
                    className="inline-flex items-center gap-2 rounded-md border border-border bg-brand px-3 py-1.5 text-body-sm text-brand-fg transition-colors hover:bg-gold hover:text-text"
                >
                    <LuArrowLeft className="h-4 w-4" />
                    Go Back
                </Button>
            </div>

            {/* Summary cards */}
            <div className="flex gap-4">
                <StatCard label="Total Files" value={batch_info.total_jobs} sub="Total files in batch" icon={<LuActivity className="h-5 w-5 text-purple-500" />} />
                <StatCard label="Processed" value={batch_info.completed_jobs} sub={`${batch_info.total_jobs > 0 ? Math.round((batch_info.completed_jobs / batch_info.total_jobs) * 100) : 0}% success rate`} icon={<LuCircleCheck className="h-5 w-5 text-status-green-fg" />} />
                <StatCard label="Failed" value={batch_info.failed_jobs} sub="Requires attention" icon={<LuCircleX className="h-5 w-5 text-status-red-fg" />} />
                <StatCard label="End Time" value={formatDate(batch_info.completed_at).split(",")[1]} sub={batch_info.completed_at ? "Completion time" : "Still processing"} icon={<LuClock className="h-5 w-5 text-text-subtle" />} />
            </div>

            {/* Files table panel */}
            <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-surface overflow-hidden">

                {/* Toolbar */}
                <div className="flex items-center justify-between gap-4 border-b border-border px-5 py-3">
                    <div className="flex items-center gap-3">
                        <h2 className="text-body-lg font-semibold text-text">Files in Batch</h2>
                        {selectedIds.size > 0 && (
                            <span className="rounded-full bg-brand-subtle px-2 py-0.5 text-label-sm text-brand font-semibold">
                                {selectedIds.size} selected
                            </span>
                        )}
                    </div>
                    <div className="flex items-center gap-3">
                        <SearchInput
                            value={search}
                            placeholder="Search files..."
                            onChange={(v) => { setSearch(v); setCurrentPage(1); setSelectedIds(new Set()); }}
                        />
                        {/* Filter dropdown */}
                        <div className="relative">
                            <button
                                onClick={() => setFilterOpen((o) => !o)}
                                className="flex items-center gap-2 rounded-md border border-border bg-bg px-3 py-1.5 text-body-sm text-text-subtle hover:bg-surface-raised hover:text-text transition-colors"
                            >
                                <LuFilter className="h-3.5 w-3.5" />
                                <span>Filter{activeFilter !== 'ALL' ? `: ${activeFilter}` : ''}</span>
                                <LuChevronDown className="h-3.5 w-3.5" />
                            </button>
                            {filterOpen && (
                                <div className="app-scrollbar absolute right-0 top-full mt-1 z-20 w-52 max-h-56 overflow-y-auto rounded-lg border border-border bg-surface shadow-lg">
                                    {FILTER_OPTIONS.map((opt) => (
                                        <button
                                            key={opt.value}
                                            onClick={() => {
                                                setActiveFilter(opt.value);
                                                setFilterOpen(false);
                                                setCurrentPage(1);
                                            }}
                                            className={`flex w-full items-center px-4 py-2 text-body-sm transition-colors ${activeFilter === opt.value
                                                ? 'bg-brand-subtle text-brand font-medium'
                                                : 'text-text-subtle hover:bg-surface-raised hover:text-text'
                                                }`}
                                        >
                                            {opt.label}
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>
                    </div>
                </div>

                {/* Table */}
                <div className="app-scrollbar min-h-0 flex-1 overflow-auto">
                    <table className="w-full min-w-[1100px] table-fixed">
                        <colgroup>
                            <col className="w-[18%]" />
                            <col className="w-[16%]" />
                            <col className="w-[9rem]" />
                            <col />
                            <col className="w-[11rem]" />
                            <col className="w-[6.5rem]" />
                        </colgroup>
                        <thead className="sticky top-0 z-10">
                            <tr className="border-b border-border bg-bg">
                                {([
                                    { label: 'FILE ID', key: 'job_id' as SortKey },
                                    { label: 'SITE VISIT ID', key: 'file_name' as SortKey },
                                    { label: 'STATUS' },
                                    { label: 'ERROR' },
                                    { label: 'CREATED', key: 'created_at' as SortKey },
                                    { label: 'ACTIONS', key: null },
                                ] as Array<{ label: string; key?: SortKey | null }>).map(({ label, key }) =>
                                    key ? (
                                        <th
                                            key={label}
                                            onClick={() => handleSort(key)}
                                            className="px-5 py-3 text-left text-label-sm text-text-disabled tracking-widest whitespace-nowrap cursor-pointer select-none"
                                        >
                                            <span className="inline-flex items-center gap-1.5 hover:text-text transition-colors">
                                                {label}
                                                <SortIcon colKey={key} />
                                            </span>
                                        </th>
                                    ) : (
                                        <th key={label} className="px-5 py-3 text-left text-label-sm text-text-disabled tracking-widest whitespace-nowrap">
                                            {label}
                                        </th>
                                    )
                                )}
                            </tr>
                        </thead>
                        <tbody>
                            {isLoading ? (
                                <TableLoading colSpan={6} />
                            ) : jobs.length === 0 ? (
                                <TableEmpty colSpan={6} message="No files match your search." />
                            ) : (
                                jobs.map((job: Job, idx: number) => {
                                    const isSelected = selectedIds.has(job.job_id);
                                    return (
                                        <tr
                                            key={job.job_id}
                                            onClick={() => toggleRow(job.job_id)}
                                            className={`border-b border-border transition-colors cursor-pointer hover:bg-surface-raised ${isSelected
                                                ? 'bg-brand-subtle/60'
                                                : idx % 2 === 0 ? '' : 'bg-bg/40'
                                                }`}
                                        >
                                            <td className="px-5 py-4 align-top text-body-sm text-text-subtle font-mono break-all">{job.job_id}</td>
                                            <td className="px-5 py-4 align-top text-body-sm font-medium text-text break-words">{job.file_name}</td>
                                            <td className="px-5 py-4 align-top whitespace-nowrap">
                                                <JobStatusBadge status={job.status} />
                                            </td>
                                            <td className="px-5 py-4 align-top text-xs leading-5 text-status-red-fg break-words">
                                                {(job.status === 'FAILED' || job.status === 'ERROR') && job.error_message
                                                    ? job.error_message
                                                    : <span className="text-text-disabled">—</span>}
                                            </td>
                                            <td className="px-5 py-4 align-top text-body-sm text-text-subtle whitespace-nowrap">{formatDate(job.created_at)}</td>
                                            <td className="px-5 py-4 align-top">
                                                {job.status === "FAILED" || job.status === "ERROR" ? (
                                                    <span className="text-body-sm text-text-disabled">—</span>
                                                ) : (
                                                    <Link href={`/files/${job.job_id}`} onClick={(e) => e.stopPropagation()}>
                                                        <Button variant="action">
                                                            View
                                                        </Button>
                                                    </Link>
                                                )}
                                            </td>
                                        </tr>
                                    );
                                })
                            )}
                        </tbody>
                    </table>
                </div>

                {/* Pagination */}
                <Pagination
                    currentPage={metadata.current_page}
                    totalPages={metadata.total_pages}
                    pageSize={metadata.page_size}
                    pageSizeOptions={PAGE_SIZE_OPTIONS}
                    totalItems={metadata.total_items}
                    showingFrom={showingFrom}
                    showingTo={showingTo}
                    itemLabel={`file${metadata.total_items !== 1 ? 's' : ''}`}
                    extraInfo={extraInfo}
                    selectId="job-page-size"
                    onPageChange={setCurrentPage}
                    onPageSizeChange={(size) => { setPageSize(size); setCurrentPage(1); }}
                />
            </div>
        </div>
    );
}
