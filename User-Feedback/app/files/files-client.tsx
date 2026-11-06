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
import { currentWeekValue, datesForIsoWeek } from '@/lib/reports/period';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { LuArrowUpDown, LuArchive, LuChevronDown, LuChevronUp, LuDownload, LuLoader } from 'react-icons/lu';
import { toast } from 'sonner';

const OUTCOME_OPTIONS = [
    { label: 'Successful', value: 'successful' },
    { label: 'No insights', value: 'no_insights' },
    { label: 'Too few words', value: 'few_words' },
    { label: 'Recording too short', value: 'short_audio' },
    { label: 'Errors', value: 'errors' },
    { label: 'All failed', value: 'failed' },
] as const;

const STATUS_OPTIONS: Array<{ label: string; value: JobStatus }> = [
    { label: 'Pending', value: 'PENDING' },
    { label: 'Batched', value: 'BATCHED' },
    { label: 'STT Submitted', value: 'STT_SUBMITTED' },
    { label: 'STT Completed', value: 'STT_COMPLETED' },
    { label: 'Processing', value: 'PROCESSING' },
    { label: 'Completed', value: 'COMPLETED' },
    { label: 'Failed', value: 'FAILED' },
    { label: 'Error', value: 'ERROR' },
];

const FILTER_OPTIONS: Array<{ label: string; value: string }> = [
    { label: 'All', value: 'ALL' },
    ...OUTCOME_OPTIONS,
    ...STATUS_OPTIONS,
];

const OUTCOME_VALUES = new Set<string>(OUTCOME_OPTIONS.map((option) => option.value));

function parseFilterValue(value: string | null | undefined): string {
    if (!value || value === 'ALL') return 'ALL';
    if (OUTCOME_VALUES.has(value)) return value;
    if (STATUS_OPTIONS.some((option) => option.value === value)) return value;
    return 'ALL';
}

const PAGE_SIZE_OPTIONS = [5, 10, 20, 50];

function formatAudioDuration(seconds: number | null | undefined): string {
    if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return '—';
    const whole = Math.floor(seconds);
    const minutes = Math.floor(whole / 60);
    const rest = whole % 60;
    return `${minutes}:${String(rest).padStart(2, '0')}`;
}

const MAX_BULK_DAYS = 7;

function shiftDate(date: string, days: number): string {
    const value = new Date(`${date}T00:00:00.000Z`);
    value.setUTCDate(value.getUTCDate() + days);
    return value.toISOString().slice(0, 10);
}

function inclusiveDays(startDate: string, endDate: string): number {
    const startMs = Date.parse(`${startDate}T00:00:00.000Z`);
    const endMs = Date.parse(`${endDate}T00:00:00.000Z`);
    return Math.floor((endMs - startMs) / 86_400_000) + 1;
}

export default function FilesClient() {
    const searchParams = useSearchParams();
    const urlKey = searchParams.toString();
    const browserTimezone = useMemo(
        () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC',
        [],
    );
    const initialFromUrl = useMemo(() => {
        const params = new URLSearchParams(urlKey);
        const filter = parseFilterValue(params.get('outcome') || params.get('status'));
        return {
            search: params.get('search') || '',
            startDate: params.get('start_date') || '',
            endDate: params.get('end_date') || '',
            filter,
            siteNumber: params.get('site_number') || '',
            userTimezone: params.get('user_timezone') || browserTimezone,
        };
    }, [urlKey, browserTimezone]);

    const [tab, setTab] = useState<'files' | 'bulk'>('files');
    const [bulkMode, setBulkMode] = useState<'weekly' | 'custom'>('weekly');
    const [bulkWeek, setBulkWeek] = useState(currentWeekValue);
    const [bulkStartDate, setBulkStartDate] = useState('');
    const [bulkEndDate, setBulkEndDate] = useState('');
    const [bulkDownloading, setBulkDownloading] = useState(false);
    type SortKey = 'job_id' | 'batch_id' | 'file_name' | 'audio_duration_seconds' | 'created_at';
    type SortDir = 'asc' | 'desc' | null;

    const [search, setSearch] = useState(initialFromUrl.search);
    const [startDate, setStartDate] = useState(initialFromUrl.startDate);
    const [endDate, setEndDate] = useState(initialFromUrl.endDate);
    const [activeFilter, setActiveFilter] = useState(initialFromUrl.filter);
    const [applied, setApplied] = useState({
        search: initialFromUrl.search,
        startDate: initialFromUrl.startDate,
        endDate: initialFromUrl.endDate,
        filter: initialFromUrl.filter,
        siteNumber: initialFromUrl.siteNumber,
        userTimezone: initialFromUrl.userTimezone,
    });
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize, setPageSize] = useState(10);
    const [sortKey, setSortKey] = useState<SortKey | null>('created_at');
    const [sortDir, setSortDir] = useState<SortDir>('desc');

    // Keep form + applied filters in sync when arriving from compliance deep-links.
    useEffect(() => {
        setSearch(initialFromUrl.search);
        setStartDate(initialFromUrl.startDate);
        setEndDate(initialFromUrl.endDate);
        setActiveFilter(initialFromUrl.filter);
        setApplied({
            search: initialFromUrl.search,
            startDate: initialFromUrl.startDate,
            endDate: initialFromUrl.endDate,
            filter: initialFromUrl.filter,
            siteNumber: initialFromUrl.siteNumber,
            userTimezone: initialFromUrl.userTimezone,
        });
        setCurrentPage(1);
        setTab('files');
    }, [initialFromUrl]);

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
        setApplied({
            search,
            startDate,
            endDate,
            filter: activeFilter,
            siteNumber: applied.siteNumber,
            userTimezone: applied.userTimezone || browserTimezone,
        });
        setCurrentPage(1);
    };

    const downloadBulkArchive = async () => {
        let startDate = bulkStartDate;
        let endDate = bulkEndDate;
        if (bulkMode === 'weekly') {
            const range = datesForIsoWeek(bulkWeek);
            if (!range.start_date || !range.end_date) {
                toast.error('Choose a week to download.');
                return;
            }
            startDate = range.start_date;
            endDate = range.end_date;
        } else if (!startDate || !endDate) {
            toast.error('Choose both a start date and an end date.');
            return;
        }
        if (startDate > endDate) {
            toast.error('Start date must be on or before the end date.');
            return;
        }
        if (inclusiveDays(startDate, endDate) > MAX_BULK_DAYS) {
            toast.error('Choose a date range within one week (7 days).');
            return;
        }

        setBulkDownloading(true);
        let objectUrl: string | undefined;
        try {
            const params = new URLSearchParams({ start_date: startDate, end_date: endDate });
            const response = await fetch(`/bff/files/bulk-download?${params.toString()}`, {
                credentials: 'same-origin',
                cache: 'no-store',
            });
            const contentType = response.headers.get('content-type') || '';
            if (!response.ok) {
                const payload = contentType.includes('application/json')
                    ? await response.json().catch(() => null)
                    : null;
                throw new Error(payload?.error || 'Could not prepare audio ZIP.');
            }

            const blob = await response.blob();
            const disposition = response.headers.get('content-disposition') || '';
            const matchedName = /filename="([^"]+)"/i.exec(disposition)?.[1];
            const filename = matchedName || `audio-files_${startDate}_to_${endDate}.zip`;
            objectUrl = URL.createObjectURL(blob);
            const anchor = document.createElement('a');
            anchor.href = objectUrl;
            anchor.download = filename;
            document.body.appendChild(anchor);
            anchor.click();
            anchor.remove();
            toast.success('Download started.');
        } catch (error) {
            toast.error(error instanceof Error ? error.message : 'Could not download audio files.');
        } finally {
            if (objectUrl) window.setTimeout(() => URL.revokeObjectURL(objectUrl!), 60_000);
            setBulkDownloading(false);
        }
    };

    const outcomeFilter = OUTCOME_VALUES.has(applied.filter) ? applied.filter : undefined;
    const statusFilter = !outcomeFilter && applied.filter !== 'ALL' ? applied.filter : undefined;

    const { data: response, isLoading, isError } = useJobs({
        page: currentPage,
        size: pageSize,
        search: applied.search || undefined,
        status: statusFilter,
        outcome: outcomeFilter,
        site_number: applied.siteNumber || undefined,
        start_date: applied.startDate || undefined,
        end_date: applied.endDate || undefined,
        user_timezone: applied.userTimezone || browserTimezone,
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
                <section className="relative rounded-lg border border-border bg-surface p-6">
                    {bulkDownloading ? (
                        <div className="absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 rounded-lg bg-surface/90 backdrop-blur-[1px]">
                            <LuLoader className="h-8 w-8 animate-spin text-brand" />
                            <p className="text-body-md font-medium text-text">Preparing ZIP…</p>
                            <p className="text-body-sm text-text-subtle">This can take a few minutes for larger weeks.</p>
                        </div>
                    ) : null}
                    <h2 className="text-h3 font-semibold text-text">Bulk audio download</h2>
                    <p className="mt-1 text-body-sm text-text-subtle">Download recordings for one week per ZIP.</p>
                    <div className="mt-5 flex flex-wrap items-end gap-4">
                        <label className="flex flex-col gap-1 text-label-sm text-text-subtle">Download type
                            <Select
                                value={bulkMode}
                                onChange={(value) => setBulkMode(value as 'weekly' | 'custom')}
                                options={[{ label: 'Weekly', value: 'weekly' }, { label: 'Custom', value: 'custom' }]}
                                disabled={bulkDownloading}
                            />
                        </label>
                        {bulkMode === 'weekly' ? (
                            <label className="flex flex-col gap-1 text-label-sm text-text-subtle">Week
                                <input type="week" value={bulkWeek} disabled={bulkDownloading} onChange={(event) => setBulkWeek(event.target.value)} className="h-10 rounded border border-border bg-bg px-3 text-body-sm text-text disabled:opacity-60" />
                            </label>
                        ) : (
                            <>
                                <label className="flex flex-col gap-1 text-label-sm text-text-subtle">Start date
                                    <input type="date" value={bulkStartDate} disabled={bulkDownloading} min={bulkEndDate ? shiftDate(bulkEndDate, -(MAX_BULK_DAYS - 1)) : undefined} max={bulkEndDate || undefined} onChange={(event) => {
                                        const value = event.target.value;
                                        setBulkStartDate(value);
                                        if (bulkEndDate && inclusiveDays(value, bulkEndDate) > MAX_BULK_DAYS) setBulkEndDate('');
                                    }} className="h-10 rounded border border-border bg-bg px-3 text-body-sm text-text disabled:opacity-60" />
                                </label>
                                <label className="flex flex-col gap-1 text-label-sm text-text-subtle">End date
                                    <input type="date" value={bulkEndDate} disabled={bulkDownloading} min={bulkStartDate || undefined} max={bulkStartDate ? shiftDate(bulkStartDate, MAX_BULK_DAYS - 1) : undefined} onChange={(event) => {
                                        const value = event.target.value;
                                        setBulkEndDate(value);
                                        if (bulkStartDate && inclusiveDays(bulkStartDate, value) > MAX_BULK_DAYS) setBulkStartDate('');
                                    }} className="h-10 rounded border border-border bg-bg px-3 text-body-sm text-text disabled:opacity-60" />
                                </label>
                            </>
                        )}
                        <Button type="button" onClick={downloadBulkArchive} disabled={bulkDownloading || (bulkMode === 'weekly' ? !bulkWeek : !bulkStartDate || !bulkEndDate)}>
                            {bulkDownloading ? <LuLoader className="mr-2 h-4 w-4 animate-spin" /> : <LuDownload className="mr-2 h-4 w-4" />}
                            {bulkDownloading ? 'Preparing ZIP…' : 'Download ZIP'}
                        </Button>
                    </div>
                    <p className="mt-4 text-xs text-text-disabled">Weekly and custom ranges are limited to 7 days. Only recordings you are authorized to access are included; missing audio files are skipped.</p>
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

                    <div className="w-56">
                        <Select
                            value={activeFilter}
                            onChange={setActiveFilter}
                            options={FILTER_OPTIONS}
                        />
                    </div>
                    <Button type="button" onClick={applyFilters}>Apply filters</Button>
                    {applied.siteNumber ? (
                        <button
                            type="button"
                            className="rounded border border-border bg-bg px-2.5 py-1 text-xs text-text-subtle hover:border-brand hover:text-brand"
                            onClick={() => {
                                setApplied((prev) => ({ ...prev, siteNumber: '' }));
                                setCurrentPage(1);
                            }}
                            title="Clear site filter"
                        >
                            Site: {applied.siteNumber} ×
                        </button>
                    ) : null}
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
