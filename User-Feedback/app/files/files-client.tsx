"use client";

import { JobStatusBadge } from '@/components/monitor/JobStatusBadge';
import { Pagination } from '@/components/ui/Pagination';
import { SearchInput } from '@/components/ui/SearchInput';
import { Button } from '@/components/ui/button';
import { Select } from '@/components/ui/Select';
import { TableEmpty, TableLoading } from '@/components/ui/TableStatus';
import { useJobs } from '@/lib/hooks/queries';
import { useDebouncedValue } from '@/lib/hooks/useDebouncedValue';
import type { Job, JobStatus, PaginationMeta } from '@/lib/monitor/types';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { LuArrowUpDown, LuChevronDown, LuChevronUp, LuFilter } from 'react-icons/lu';
import { toast } from 'sonner';

const FILTER_OPTIONS: Array<{ label: string; value: JobStatus | 'ALL' }> = [
    { label: 'All Status', value: 'ALL' },
    { label: 'Pending', value: 'PENDING' },
    { label: 'Batched', value: 'BATCHED' },
    { label: 'STT Submitted', value: 'STT_SUBMITTED' },
    { label: 'STT Completed', value: 'STT_COMPLETED' },
    { label: 'Processing', value: 'PROCESSING' },
    { label: 'Completed', value: 'COMPLETED' },
    { label: 'Failed', value: 'FAILED' },
    { label: 'Error', value: 'ERROR' }
];

const PAGE_SIZE_OPTIONS = [5, 10, 20, 50];

export default function FilesClient() {
    type SortKey = 'job_id' | 'batch_id' | 'file_name' | 'created_at';
    type SortDir = 'asc' | 'desc' | null;

    const [search, setSearch] = useState('');
    const [activeFilter, setActiveFilter] = useState<JobStatus | 'ALL'>('ALL');
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
        } else {
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

    const { data: response, isLoading, isError } = useJobs({
        page: currentPage,
        size: pageSize,
        search: debouncedSearch,
        status: activeFilter,
        sort_by: sortKey || undefined,
        sort_dir: sortDir || undefined,
    });

    useEffect(() => {
        if (isError) {
            toast.error("Failed to load files data.");
        }
    }, [isError]);

    const jobs: Job[] = response?.data?.items || [];

    const metadata: PaginationMeta = {
        total_items: response?.data?.metadata?.total_items || 0,
        total_pages: response?.data?.metadata?.total_pages || 1,
        current_page: response?.data?.metadata?.current_page || 1,
        page_size: response?.data?.metadata?.page_size || pageSize,
        has_next: response?.data?.metadata?.has_next || false,
        has_previous: response?.data?.metadata?.has_previous || false
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

    return (
        <div className="flex h-full flex-col gap-6 p-8 bg-bg">
            {/* Header */}
            <div>
                <div className="flex items-center gap-3">
                    <h1 className="text-h1 font-bold text-text">Audio Files</h1>
                    {/* {isFetching && !isLoading && (
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-subtle px-2.5 py-0.5 text-label-sm font-medium text-brand animate-pulse">
                            <LuActivity className="h-3 w-3" />
                            Syncing
                        </span>
                    )} */}
                </div>
                <p className="mt-1 text-body-md text-text-subtle">
                    Real-time status of all processed files across all batches.
                </p>
            </div>

            {/* Table Panel */}
            <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-surface overflow-hidden">

                {/* Toolbar */}
                <div className="flex items-center justify-between gap-4 border-b border-border px-5 py-3">
                    <SearchInput
                        value={search}
                        placeholder="Search by file or batch ID..."
                        onChange={(v) => { setSearch(v); setCurrentPage(1); }}
                    />

                    {/* Filter dropdown */}
                    <div className="w-48">
                        <Select
                            value={activeFilter}
                            onChange={(v) => {
                                setActiveFilter(v as JobStatus | 'ALL');
                                setCurrentPage(1);
                            }}
                            options={FILTER_OPTIONS}
                        />
                    </div>
                </div>

                {/* Table */}
                <div className="app-scrollbar min-h-0 flex-1 overflow-auto">
                    <table className="w-full min-w-[1200px] table-fixed">
                        <colgroup>
                            <col className="w-[16%]" />
                            <col className="w-[14%]" />
                            <col className="w-[14%]" />
                            <col className="w-[9rem]" />
                            <col />
                            <col className="w-[11rem]" />
                            <col className="w-[6.5rem]" />
                        </colgroup>
                        <thead className="sticky top-0 z-10">
                            <tr className="border-b border-border bg-bg">
                                {([
                                    { label: 'FILE ID', key: 'job_id' as SortKey },
                                    { label: 'BATCH ID', key: 'batch_id' as SortKey },
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
                                <TableLoading colSpan={7} />
                            ) : jobs.length === 0 ? (
                                <TableEmpty colSpan={7} message="No files match your search." />
                            ) : (
                                jobs.map((job: Job, idx: number) => (
                                    <tr
                                        key={job.job_id}
                                        className={`border-b border-border transition-colors ${idx % 2 === 0 ? '' : 'bg-bg/40'
                                            }`}
                                    >
                                        <td className="px-5 py-4 align-top text-body-sm font-mono text-text-subtle break-all">
                                            {job.job_id}
                                        </td>
                                        <td className="px-5 py-4 align-top">
                                            <Link
                                                href={`/monitor/batches/${job.batch_id}`}
                                                className="text-body-sm font-mono font-semibold text-brand hover:underline underline-offset-2 break-all"
                                            >
                                                {job.batch_id}
                                            </Link>
                                        </td>
                                        <td className="px-5 py-4 align-top text-body-sm font-medium text-text break-words">
                                            {job.file_name}
                                        </td>
                                        <td className="px-5 py-4 align-top whitespace-nowrap">
                                            <JobStatusBadge status={job.status} />
                                        </td>
                                        <td className="px-5 py-4 align-top text-xs leading-5 text-status-red-fg break-words">
                                            {(job.status === 'FAILED' || job.status === 'ERROR') && job.error_message
                                                ? job.error_message
                                                : <span className="text-text-disabled">—</span>}
                                        </td>
                                        <td className="px-5 py-4 align-top text-body-sm text-text-subtle whitespace-nowrap">
                                            {formatDate(job.created_at)}
                                        </td>
                                        <td className="px-5 py-4 align-top">
                                            {job.status === "FAILED" || job.status === "ERROR" ? (
                                                <span className="text-body-sm text-text-disabled">—</span>
                                            ) : (
                                                <Link href={`/files/${job.job_id}`}>
                                                    <Button variant="action">View</Button>
                                                </Link>
                                            )}
                                        </td>
                                    </tr>
                                ))
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
                    itemLabel="files"
                    selectId="files-page-size"
                    onPageChange={setCurrentPage}
                    onPageSizeChange={(size) => { setPageSize(size); setCurrentPage(1); }}
                />
            </div>
        </div>
    );
}
