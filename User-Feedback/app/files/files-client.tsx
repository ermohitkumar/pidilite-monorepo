"use client";

import { JobStatusBadge } from '@/components/monitor/JobStatusBadge';
import { AudioPlayer } from '@/components/reports/AudioPlayer';
import { Pagination } from '@/components/ui/Pagination';
import { DateRangeFilter } from '@/components/ui/DateRangeFilter';
import { SearchInput } from '@/components/ui/SearchInput';
import { Button } from '@/components/ui/button';
import { Select } from '@/components/ui/Select';
import { TableEmpty, TableLoading } from '@/components/ui/TableStatus';
import { useJobs } from '@/lib/hooks/queries';
import type { Job, JobStatus, PaginationMeta } from '@/lib/monitor/types';
import { formatPipelineError } from '@/lib/monitor/format-error';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import { LuArrowUpDown, LuArchive, LuChevronDown, LuChevronUp, LuDownload } from 'react-icons/lu';
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

function formatAudioDuration(seconds: number | null | undefined): string {
    if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return '—';
    const whole = Math.floor(seconds);
    const minutes = Math.floor(whole / 60);
    const rest = whole % 60;
    return `${minutes}:${String(rest).padStart(2, '0')}`;
}

function monthStart(date: string): string {
    return `${date.slice(0, 7)}-01`;
}

function monthEnd(date: string): string {
    const [year, month] = date.slice(0, 7).split('-').map(Number);
    return `${date.slice(0, 7)}-${String(new Date(Date.UTC(year, month, 0)).getUTCDate()).padStart(2, '0')}`;
}

export default function FilesClient() {
    const [tab, setTab] = useState<'files' | 'bulk'>('files');
    const [bulkMode, setBulkMode] = useState<'monthly' | 'custom'>('monthly');
    const [bulkMonth, setBulkMonth] = useState('');
    const [bulkStartDate, setBulkStartDate] = useState('');
    const [bulkEndDate, setBulkEndDate] = useState('');
    const [bulkDownloading, setBulkDownloading] = useState(false);
    type SortKey = 'job_id' | 'batch_id' | 'file_name' | 'audio_duration_seconds' | 'created_at';
    type SortDir = 'asc' | 'desc' | null;

    const [search, setSearch] = useState('');
    const [startDate, setStartDate] = useState('');
    const [endDate, setEndDate] = useState('');
    const [activeFilter, setActiveFilter] = useState<JobStatus | 'ALL'>('ALL');
    const [applied, setApplied] = useState({
        search: '',
        startDate: '',
        endDate: '',
        status: 'ALL' as JobStatus | 'ALL',
    });
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize, setPageSize] = useState(10);
    const [sortKey, setSortKey] = useState<SortKey | null>('created_at');
    const [sortDir, setSortDir] = useState<SortDir>('desc');

    const handleSort = (key: SortKey) => {
        if (sortKey !== key) {
            setSortKey(key);
            setSortDir('asc');
        } else {
            setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
        }
        setCurrentPage(1);
    };

    const SortIcon = ({ colKey }: { colKey: SortKey }) => {
        if (sortKey !== colKey) return <LuArrowUpDown className="h-3 w-3 opacity-40" />;
        if (sortDir === 'asc') return <LuChevronUp className="h-3 w-3 text-brand" />;
        return <LuChevronDown className="h-3 w-3 text-brand" />;
    };

    const applyFilters = () => {
        setApplied({ search, startDate, endDate, status: activeFilter });
        setCurrentPage(1);
    };

    const downloadBulkArchive = async () => {
        let startDate = bulkStartDate;
        let endDate = bulkEndDate;
        if (bulkMode === 'monthly') {
            if (!/^\d{4}-(0[1-9]|1[0-2])$/.test(bulkMonth)) {
                toast.error('Choose a month to download.');
                return;
            }
            startDate = `${bulkMonth}-01`;
            endDate = monthEnd(startDate);
        } else if (!startDate || !endDate) {
            toast.error('Choose both a start date and an end date.');
            return;
        }
        if (startDate > endDate) {
            toast.error('Start date must be on or before the end date.');
            return;
        }
        if (startDate.slice(0, 7) !== endDate.slice(0, 7)) {
            toast.error('Choose a date range within one calendar month.');
            return;
        }

        setBulkDownloading(true);
        try {
            const params = new URLSearchParams({ start_date: startDate, end_date: endDate });
            const anchor = document.createElement('a');
            anchor.href = `/bff/files/bulk-download?${params.toString()}`;
            document.body.appendChild(anchor);
            anchor.click();
            anchor.remove();
            toast.info('Your audio ZIP is being prepared. The download will start when it is ready.');
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Could not download audio files.');
        } finally {
            window.setTimeout(() => setBulkDownloading(false), 1500);
        }
    };

    const { data: response, isLoading, isError } = useJobs({
        page: currentPage,
        size: pageSize,
        search: applied.search || undefined,
        status: applied.status,
        start_date: applied.startDate || undefined,
        end_date: applied.endDate || undefined,
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

            <div className="flex gap-1 rounded-md bg-surface p-1 self-start border border-border">
                <button type="button" className={`flex items-center gap-2 rounded px-3 py-2 text-body-sm ${tab === 'files' ? 'bg-brand-subtle text-brand font-medium' : 'text-text-subtle'}`} onClick={() => setTab('files')}>
                    <LuDownload className="h-4 w-4" /> Files
                </button>
                <button type="button" className={`flex items-center gap-2 rounded px-3 py-2 text-body-sm ${tab === 'bulk' ? 'bg-brand-subtle text-brand font-medium' : 'text-text-subtle'}`} onClick={() => setTab('bulk')}>
                    <LuArchive className="h-4 w-4" /> Bulk download
                </button>
            </div>

            {tab === 'bulk' ? (
                <section className="rounded-lg border border-border bg-surface p-6">
                    <h2 className="text-h3 font-semibold text-text">Bulk audio download</h2>
                    <p className="mt-1 text-body-sm text-text-subtle">Download recordings for one calendar month per ZIP.</p>
                    <div className="mt-5 flex flex-wrap items-end gap-4">
                        <label className="flex flex-col gap-1 text-label-sm text-text-subtle">Download type
                            <Select
                                value={bulkMode}
                                onChange={(value) => setBulkMode(value as 'monthly' | 'custom')}
                                options={[{ label: 'Monthly', value: 'monthly' }, { label: 'Custom', value: 'custom' }]}
                            />
                        </label>
                        {bulkMode === 'monthly' ? (
                            <label className="flex flex-col gap-1 text-label-sm text-text-subtle">Month
                                <input type="month" value={bulkMonth} onChange={(event) => setBulkMonth(event.target.value)} className="h-10 rounded border border-border bg-bg px-3 text-body-sm text-text" />
                            </label>
                        ) : (
                            <>
                                <label className="flex flex-col gap-1 text-label-sm text-text-subtle">Start date
                                    <input type="date" value={bulkStartDate} min={bulkEndDate ? monthStart(bulkEndDate) : undefined} max={bulkEndDate || (bulkStartDate ? monthEnd(bulkStartDate) : undefined)} onChange={(event) => {
                                        const value = event.target.value;
                                        setBulkStartDate(value);
                                        if (bulkEndDate && value.slice(0, 7) !== bulkEndDate.slice(0, 7)) setBulkEndDate('');
                                    }} className="h-10 rounded border border-border bg-bg px-3 text-body-sm text-text" />
                                </label>
                                <label className="flex flex-col gap-1 text-label-sm text-text-subtle">End date
                                    <input type="date" value={bulkEndDate} min={bulkStartDate || (bulkEndDate ? monthStart(bulkEndDate) : undefined)} max={bulkStartDate ? monthEnd(bulkStartDate) : (bulkEndDate ? monthEnd(bulkEndDate) : undefined)} onChange={(event) => {
                                        const value = event.target.value;
                                        setBulkEndDate(value);
                                        if (bulkStartDate && value.slice(0, 7) !== bulkStartDate.slice(0, 7)) setBulkStartDate('');
                                    }} className="h-10 rounded border border-border bg-bg px-3 text-body-sm text-text" />
                                </label>
                            </>
                        )}
                        <Button type="button" onClick={downloadBulkArchive} disabled={bulkDownloading || (bulkMode === 'monthly' ? !bulkMonth : !bulkStartDate || !bulkEndDate)}>
                            <LuDownload className="mr-2 h-4 w-4" />{bulkDownloading ? 'Preparing ZIP…' : 'Download ZIP'}
                        </Button>
                    </div>
                    <p className="mt-4 text-xs text-text-disabled">Custom dates must stay within one calendar month. Only recordings you are authorized to access are included; missing audio files are skipped.</p>
                </section>
            ) : (
            /* Table Panel */
            <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-surface overflow-hidden">

                {/* Toolbar */}
                <div className="flex flex-wrap items-center justify-between gap-4 border-b border-border px-5 py-3">
                    <SearchInput
                        value={search}
                        placeholder="Search by file or batch ID..."
                        onChange={setSearch}
                    />
                    <DateRangeFilter
                        startDate={startDate}
                        endDate={endDate}
                        onStartDateChange={setStartDate}
                        onEndDateChange={setEndDate}
                    />

                    <div className="w-48">
                        <Select
                            value={activeFilter}
                            onChange={(v) => setActiveFilter(v as JobStatus | 'ALL')}
                            options={FILTER_OPTIONS}
                        />
                    </div>
                    <Button type="button" onClick={applyFilters}>Apply filters</Button>
                </div>

                {/* Table */}
                <div className="app-scrollbar min-h-0 flex-1 overflow-auto">
                    <table className="w-full min-w-[1320px] table-fixed">
                        <colgroup>
                            <col className="w-[15%]" />
                            <col className="w-[13%]" />
                            <col className="w-[13%]" />
                            <col className="w-[6.5rem]" />
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
                                    { label: 'FILE NAME', key: 'file_name' as SortKey },
                                    { label: 'DURATION', key: 'audio_duration_seconds' as SortKey },
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
                                <TableLoading colSpan={8} />
                            ) : jobs.length === 0 ? (
                                <TableEmpty colSpan={8} message="No files match your search." />
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
                                        <td className="px-5 py-4 align-top text-body-sm font-mono text-text-subtle whitespace-nowrap">
                                            {formatAudioDuration(job.audio_duration_seconds)}
                                        </td>
                                        <td className="px-5 py-4 align-top whitespace-nowrap">
                                            <JobStatusBadge status={job.status} />
                                        </td>
                                        <td className="px-5 py-4 align-top text-xs leading-5 text-status-red-fg break-words">
                                            {(job.status === 'FAILED' || job.status === 'ERROR') && job.error_message
                                                ? formatPipelineError(job.error_message)
                                                : <span className="text-text-disabled">—</span>}
                                        </td>
                                        <td className="px-5 py-4 align-top text-body-sm text-text-subtle whitespace-nowrap">
                                            {formatDate(job.created_at)}
                                        </td>
                                        <td className="px-5 py-4 align-top">
                                            <div className="flex flex-wrap items-center gap-2">
                                                <AudioPlayer
                                                    jobId={job.job_id}
                                                    fileName={job.file_name || undefined}
                                                    durationSeconds={job.audio_duration_seconds}
                                                    showDownload
                                                />
                                                <Link href={`/files/${job.job_id}`}>
                                                    <Button variant="action">View</Button>
                                                </Link>
                                            </div>
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
            )}
        </div>
    );
}
