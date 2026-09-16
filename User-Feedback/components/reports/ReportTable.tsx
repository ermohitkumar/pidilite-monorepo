"use client";

import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { LuArrowDown, LuArrowUp, LuSettings2 } from "react-icons/lu";

import { AudioPlayer } from "@/components/reports/AudioPlayer";
import { FileSourceLink } from "@/components/reports/FileSourceLink";
import { Pagination } from "@/components/ui/Pagination";
import { COLUMN_LABELS, type MatrixColumn, type MatrixRow } from "@/lib/reports/types";

const DETAIL_COLUMNS = new Set<MatrixColumn>([
    "feedback_summary_ai",
    "feedback_excerpt",
    "full_conversation",
]);

const META_COLUMNS = new Set<MatrixColumn>(["file_name", "call_datetime", "audio"]);

type SortDir = "asc" | "desc";

export type ContextChip = { label: string; value: string };

const DATETIME_FORMAT: Intl.DateTimeFormatOptions = {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
};

function formatReportDateTime(value?: string | null): string {
    const raw = (value || "").trim();
    if (!raw) return "";
    if (/^\d{4}-\d{2}-\d{2}$/.test(raw)) {
        const parsed = new Date(`${raw}T00:00:00`);
        if (Number.isNaN(parsed.getTime())) return raw;
        return new Intl.DateTimeFormat("en-IN", {
            timeZone: "Asia/Kolkata",
            day: "2-digit",
            month: "short",
            year: "numeric",
        }).format(parsed);
    }
    const parsed = new Date(raw);
    if (Number.isNaN(parsed.getTime())) return raw;
    return new Intl.DateTimeFormat("en-IN", DATETIME_FORMAT).format(parsed);
}

function totalLabel(row: MatrixRow): string {
    return row.product_name || row.feedback_category || row.feedback_group || row.total_label || "";
}

function cellValue(row: MatrixRow, column: MatrixColumn): string {
    if (row.kind === "total") {
        const labelCol: MatrixColumn = row.product_name
            ? "product_name"
            : row.feedback_category
              ? "feedback_category"
              : "feedback_group";
        if (column === labelCol) return totalLabel(row);
        if (column === "feedback_count") {
            return row.feedback_count == null ? "" : String(row.feedback_count);
        }
        if (column === "feedback_tag") return row.feedback_tag || "";
        if (column === "feedback_sub_tag") return row.feedback_sub_tag || "";
        return "";
    }
    if (column === "feedback_count") {
        if (row.feedback_count === null || row.feedback_count === undefined) return "";
        return String(row.feedback_count);
    }
    if (column === "call_datetime") {
        return formatReportDateTime(row.call_datetime);
    }
    if (column === "audio") return "";
    const value = row[column];
    if (value === null || value === undefined) return "";
    return String(value);
}

function isCountCell(row: MatrixRow, column: MatrixColumn, value: string): boolean {
    if (!value || value === "0") return false;
    if (column === "feedback_count") return true;
    return (
        row.kind === "total" &&
        (column === "feedback_tag" || column === "feedback_sub_tag") &&
        /^\d+$/.test(value)
    );
}

function constantValues(rows: MatrixRow[], columns: MatrixColumn[]): Partial<Record<MatrixColumn, string>> {
    const data = rows.filter((row) => row.kind === "data");
    if (data.length === 0) return {};
    const found: Partial<Record<MatrixColumn, string>> = {};
    for (const column of columns) {
        if (DETAIL_COLUMNS.has(column) || META_COLUMNS.has(column) || column === "feedback_count") continue;
        const values = new Set(data.map((row) => cellValue(row, column)).filter(Boolean));
        if (values.size === 1) found[column] = [...values][0];
    }
    return found;
}

function compareRows(a: MatrixRow, b: MatrixRow, column: MatrixColumn, dir: SortDir): number {
    if (column === "call_datetime") {
        const left = Date.parse(a.call_datetime || "") || 0;
        const right = Date.parse(b.call_datetime || "") || 0;
        const result = left - right;
        return dir === "asc" ? result : -result;
    }
    const left = cellValue(a, column);
    const right = cellValue(b, column);
    const leftNum = Number(left);
    const rightNum = Number(right);
    let result = 0;
    if (left !== "" && right !== "" && !Number.isNaN(leftNum) && !Number.isNaN(rightNum)) {
        result = leftNum - rightNum;
    } else {
        result = left.localeCompare(right, undefined, { sensitivity: "base" });
    }
    return dir === "asc" ? result : -result;
}

function cellClassName(column: MatrixColumn): string {
    const parts = ["border-b border-slate-200 px-3 py-2 align-top"];
    if (column === "feedback_count") parts.push("text-center w-28");
    if (column === "call_datetime") parts.push("whitespace-nowrap w-40");
    if (column === "audio") parts.push("whitespace-nowrap w-24");
    if (column === "file_name") parts.push("min-w-[160px] max-w-[260px]");
    if (column === "feedback_summary_ai") parts.push("min-w-[280px] max-w-[520px]");
    if (column === "feedback_excerpt") {
        parts.push("min-w-[280px] max-w-[560px]");
    } else if (DETAIL_COLUMNS.has(column) && column !== "feedback_summary_ai") {
        parts.push("min-w-[220px] max-w-[360px]");
    }
    return parts.join(" ");
}

function CellContent({
    column,
    row,
    value,
    onCountClick,
    onTextClick,
}: Readonly<{
    column: MatrixColumn;
    row: MatrixRow;
    value: string;
    onCountClick?: (row: MatrixRow) => void;
    onTextClick?: (column: MatrixColumn, row: MatrixRow) => void;
}>) {
    if (isCountCell(row, column, value)) {
        return (
            <CountLink
                value={value}
                emphasize={row.kind === "total"}
                onClick={row.drill && onCountClick ? () => onCountClick(row) : undefined}
            />
        );
    }
    if (column === "audio") {
        return <AudioPlayer jobId={row.job_id} fileName={row.file_name} />;
    }
    if (column === "file_name" && value) {
        return <FileSourceLink jobId={row.job_id} fileName={value} />;
    }
    if (column === "call_datetime") {
        return <span className="tabular-nums text-slate-700">{value || "—"}</span>;
    }
    if (column === "feedback_summary_ai") {
        if (!value) return "—";
        return (
            <ClampedSummary
                value={value}
                onViewMore={
                    onTextClick && row.kind === "data" ? () => onTextClick(column, row) : undefined
                }
            />
        );
    }
    if (column === "feedback_excerpt") {
        if (onTextClick && value && row.kind === "data") {
            return (
                <button
                    type="button"
                    className="whitespace-pre-wrap break-words text-left text-slate-800 hover:underline"
                    onClick={() => onTextClick(column, row)}
                >
                    {value}
                </button>
            );
        }
        return <p className="whitespace-pre-wrap break-words text-slate-800">{value}</p>;
    }
    if (column === "full_conversation") {
        if (!row.feedback_id) return value || "";
        return (
            <button
                type="button"
                className="text-left text-xs font-semibold text-brand hover:underline"
                onClick={() => onTextClick?.(column, row)}
            >
                View full conversation
            </button>
        );
    }
    return value;
}

function ClampedSummary({
    value,
    onViewMore,
}: {
    value: string;
    onViewMore?: () => void;
}) {
    const textRef = useRef<HTMLParagraphElement>(null);
    const [truncated, setTruncated] = useState(false);

    useLayoutEffect(() => {
        const el = textRef.current;
        if (!el) return;
        const check = () => setTruncated(el.scrollHeight > el.clientHeight + 1);
        check();
        const observer = new ResizeObserver(check);
        observer.observe(el);
        return () => observer.disconnect();
    }, [value]);

    return (
        <div>
            <p ref={textRef} className="line-clamp-3 whitespace-pre-wrap break-words text-sm leading-6 text-slate-800">
                {value}
            </p>
            {onViewMore && truncated ? (
                <button
                    type="button"
                    className="mt-1 text-xs font-semibold text-brand hover:underline"
                    onClick={onViewMore}
                >
                    View more
                </button>
            ) : null}
        </div>
    );
}

function CountLink({
    value,
    onClick,
    emphasize,
}: Readonly<{ value: string; onClick?: () => void; emphasize?: boolean }>) {
    if (!onClick) {
        return <span className={emphasize ? "text-red-600 font-bold" : ""}>{value}</span>;
    }
    return (
        <button
            type="button"
            onClick={onClick}
            title="Show breakdown"
            className={`inline-flex min-w-8 items-center justify-center rounded-full px-2.5 py-0.5 font-semibold transition-colors ${
                emphasize
                    ? "bg-red-50 text-red-700 hover:bg-red-600 hover:text-white"
                    : "bg-brand-subtle text-brand hover:bg-brand hover:text-white"
            }`}
        >
            {value}
        </button>
    );
}

function ColumnFilter({
    column,
    options,
    value,
    onChange,
}: Readonly<{
    column: MatrixColumn;
    options: string[];
    value: string;
    onChange: (next: string) => void;
}>) {
    if (column === "audio") {
        return <span className="block h-7" />;
    }
    const compact = options.length > 0 && options.length <= 16 && !DETAIL_COLUMNS.has(column);
    if (compact) {
        return (
            <select
                value={value}
                onChange={(event) => onChange(event.target.value)}
                className="h-7 w-full rounded border border-black/10 bg-white px-1.5 text-[11px] font-normal"
                aria-label={`Filter ${COLUMN_LABELS[column]}`}
            >
                <option value="">All</option>
                {options.map((option) => (
                    <option key={option} value={option}>
                        {option}
                    </option>
                ))}
            </select>
        );
    }
    return (
        <input
            value={value}
            onChange={(event) => onChange(event.target.value)}
            placeholder="Filter"
            className="h-7 w-full rounded border border-black/10 bg-white px-1.5 text-[11px] font-normal"
            aria-label={`Filter ${COLUMN_LABELS[column]}`}
        />
    );
}

function TableSettings({
    columns,
    hidden,
    onToggle,
}: Readonly<{
    columns: MatrixColumn[];
    hidden: Set<MatrixColumn>;
    onToggle: (column: MatrixColumn) => void;
}>) {
    const [open, setOpen] = useState(false);
    const rootRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!open) return;
        const close = (event: MouseEvent) => {
            if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
        };
        document.addEventListener("mousedown", close);
        return () => document.removeEventListener("mousedown", close);
    }, [open]);

    return (
        <div className="relative" ref={rootRef}>
            <button
                type="button"
                onClick={() => setOpen((prev) => !prev)}
                className="inline-flex items-center gap-1.5 rounded-md border border-slate-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
                aria-expanded={open}
                aria-haspopup="true"
            >
                <LuSettings2 className="h-3.5 w-3.5" />
                Table settings
            </button>
            {open ? (
                <div className="absolute right-0 z-20 mt-1 w-56 rounded-md border border-slate-200 bg-white p-2 shadow-lg">
                    <p className="px-2 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400">
                        Columns
                    </p>
                    {columns.map((column) => (
                        <label
                            key={column}
                            className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm text-slate-700 hover:bg-slate-50"
                        >
                            <input
                                type="checkbox"
                                className="h-3.5 w-3.5 accent-brand"
                                checked={!hidden.has(column)}
                                onChange={() => onToggle(column)}
                            />
                            {COLUMN_LABELS[column]}
                        </label>
                    ))}
                </div>
            ) : null}
        </div>
    );
}

export type ReportTableServer = {
    page: number;
    pageSize: number;
    totalItems: number;
    sortBy?: MatrixColumn | null;
    sortDir?: SortDir | null;
    onPageChange: (page: number) => void;
    onPageSizeChange: (size: number) => void;
    onSortChange?: (sort: { column: MatrixColumn; dir: SortDir } | null) => void;
};

export function ReportTable({
    columns,
    rows,
    onCountClick,
    onTextClick,
    context,
    itemLabel = "rows",
    pageSizeOptions = [10, 20, 50],
    optionalColumns = [],
    defaultHiddenColumns = [],
    settingsStorageKey,
    serverMode,
}: Readonly<{
    columns: MatrixColumn[];
    rows: MatrixRow[];
    onCountClick?: (row: MatrixRow) => void;
    onTextClick?: (column: MatrixColumn, row: MatrixRow) => void;
    context?: ContextChip[];
    itemLabel?: string;
    pageSizeOptions?: number[];
    optionalColumns?: MatrixColumn[];
    defaultHiddenColumns?: MatrixColumn[];
    settingsStorageKey?: string;
    serverMode?: ReportTableServer;
}>) {
    const [sort, setSort] = useState<{ column: MatrixColumn; dir: SortDir } | null>(null);
    const [filters, setFilters] = useState<Partial<Record<MatrixColumn, string>>>({});
    const [page, setPage] = useState(1);
    const [pageSize, setPageSize] = useState(pageSizeOptions[0] || 10);
    const [hiddenColumns, setHiddenColumns] = useState<Set<MatrixColumn>>(
        () => new Set(defaultHiddenColumns),
    );

    useEffect(() => {
        if (!settingsStorageKey) return;
        try {
            const raw = window.localStorage.getItem(settingsStorageKey);
            if (!raw) return;
            const parsed = JSON.parse(raw) as unknown;
            if (Array.isArray(parsed)) {
                setHiddenColumns(new Set(parsed.filter((item): item is MatrixColumn => typeof item === "string")));
            }
        } catch {
            /* keep defaults */
        }
    }, [settingsStorageKey]);

    const toggleOptionalColumn = (column: MatrixColumn) => {
        setHiddenColumns((prev) => {
            const next = new Set(prev);
            if (next.has(column)) next.delete(column);
            else next.add(column);
            if (settingsStorageKey) {
                window.localStorage.setItem(settingsStorageKey, JSON.stringify([...next]));
            }
            return next;
        });
    };

    const shared = useMemo(
        () => (serverMode ? {} : constantValues(rows, columns)),
        [rows, columns, serverMode],
    );
    const visibleColumns = useMemo(
        () => columns.filter((column) => !shared[column] && !hiddenColumns.has(column)),
        [columns, shared, hiddenColumns],
    );
    const contextChips = useMemo(() => {
        const fromRows: ContextChip[] = Object.entries(shared).map(([column, value]) => ({
            label: COLUMN_LABELS[column as MatrixColumn],
            value: value || "",
        }));
        const seen = new Set(fromRows.map((chip) => `${chip.label}:${chip.value}`));
        const pinned = (context || []).filter((chip) => {
            const key = `${chip.label}:${chip.value}`;
            if (!chip.value || seen.has(key)) return false;
            seen.add(key);
            return true;
        });
        return [...pinned, ...fromRows];
    }, [context, shared]);

    const optionsByColumn = useMemo(() => {
        const map: Partial<Record<MatrixColumn, string[]>> = {};
        for (const column of visibleColumns) {
            map[column] = Array.from(
                new Set(rows.filter((row) => row.kind === "data").map((row) => cellValue(row, column)).filter(Boolean)),
            ).sort((a, b) => a.localeCompare(b));
        }
        return map;
    }, [rows, visibleColumns]);

    const prepared = useMemo(() => {
        if (serverMode) return rows;
        const dataRows = rows.filter((row) => row.kind === "data");
        const totalRows = rows.filter((row) => row.kind === "total");
        const matches = (row: MatrixRow) =>
            visibleColumns.every((column) => {
                const needle = (filters[column] || "").trim().toLowerCase();
                if (!needle) return true;
                return cellValue(row, column).toLowerCase().includes(needle);
            });
        let nextData = dataRows.filter(matches);
        if (sort) {
            nextData = [...nextData].sort((a, b) => compareRows(a, b, sort.column, sort.dir));
        }
        const nextTotals = totalRows.filter(matches);
        return [...nextData, ...nextTotals];
    }, [rows, visibleColumns, filters, sort, serverMode]);

    const activeSort = serverMode
        ? serverMode.sortBy
            ? { column: serverMode.sortBy, dir: serverMode.sortDir || "desc" }
            : null
        : sort;
    const effectivePageSize = serverMode ? serverMode.pageSize : pageSize;
    const totalItems = serverMode ? serverMode.totalItems : prepared.length;
    const totalPages = Math.max(1, Math.ceil(totalItems / effectivePageSize) || 1);
    const currentPage = serverMode ? serverMode.page : Math.min(page, totalPages);
    const start = (currentPage - 1) * effectivePageSize;
    const pageRows = serverMode ? prepared : prepared.slice(start, start + effectivePageSize);
    const showingFrom = totalItems === 0 ? 0 : start + 1;
    const showingTo = Math.min(start + effectivePageSize, totalItems);

    useEffect(() => {
        if (serverMode) return;
        setPage(1);
    }, [filters, sort, pageSize, hiddenColumns, serverMode]);

    const toggleSort = (column: MatrixColumn) => {
        const next = (prev: { column: MatrixColumn; dir: SortDir } | null) => {
            if (!prev || prev.column !== column) return { column, dir: "asc" as const };
            if (prev.dir === "asc") return { column, dir: "desc" as const };
            return null;
        };
        if (serverMode?.onSortChange) {
            serverMode.onSortChange(next(activeSort));
            return;
        }
        setSort(next);
    };

    return (
        <div className="overflow-hidden rounded-xl border border-border bg-white shadow-sm">
            {contextChips.length > 0 || optionalColumns.length > 0 ? (
                <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 bg-slate-50 px-4 py-3">
                    <div className="flex flex-wrap gap-2">
                        {contextChips.map((chip) => (
                            <div
                                key={`${chip.label}-${chip.value}`}
                                className="rounded-md border border-slate-200 bg-white px-2.5 py-1"
                            >
                                <div className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                                    {chip.label}
                                </div>
                                <div className="text-sm font-semibold text-slate-900">{chip.value}</div>
                            </div>
                        ))}
                    </div>
                    {optionalColumns.length > 0 ? (
                        <TableSettings
                            columns={optionalColumns}
                            hidden={hiddenColumns}
                            onToggle={toggleOptionalColumn}
                        />
                    ) : null}
                </div>
            ) : null}
            <div className="overflow-auto">
                <table className="min-w-full border-collapse text-[13px] text-slate-900">
                    <thead>
                        <tr>
                            {visibleColumns.map((column) => {
                                const active = activeSort?.column === column;
                                return (
                                    <th
                                        key={column}
                                        className="border-b border-black/10 bg-[#FFC000] px-3 py-2 text-left font-bold whitespace-nowrap"
                                    >
                                        {column === "audio" ? (
                                            <span>{COLUMN_LABELS[column]}</span>
                                        ) : (
                                        <button
                                            type="button"
                                            onClick={() => toggleSort(column)}
                                            className="inline-flex items-center gap-1"
                                            title={`Sort ${COLUMN_LABELS[column]}`}
                                        >
                                            {COLUMN_LABELS[column]}
                                            {active && activeSort?.dir === "asc" ? (
                                                <LuArrowUp className="h-3.5 w-3.5" />
                                            ) : active && activeSort?.dir === "desc" ? (
                                                <LuArrowDown className="h-3.5 w-3.5" />
                                            ) : (
                                                <span className="text-[10px] font-semibold text-black/40">↕</span>
                                            )}
                                        </button>
                                        )}
                                    </th>
                                );
                            })}
                        </tr>
                        {serverMode ? null : (
                        <tr>
                            {visibleColumns.map((column) => (
                                <th key={`filter-${column}`} className="border-b border-slate-200 bg-[#FFE08A] px-2 py-1.5">
                                    <ColumnFilter
                                        column={column}
                                        options={optionsByColumn[column] || []}
                                        value={filters[column] || ""}
                                        onChange={(next) =>
                                            setFilters((prev) => ({ ...prev, [column]: next }))
                                        }
                                    />
                                </th>
                            ))}
                        </tr>
                        )}
                    </thead>
                    <tbody>
                        {pageRows.length === 0 ? (
                            <tr>
                                <td
                                    className="px-3 py-10 text-center text-slate-500"
                                    colSpan={Math.max(visibleColumns.length, 1)}
                                >
                                    No feedback fact rows for this view.
                                </td>
                            </tr>
                        ) : (
                            pageRows.map((row, index) => (
                                <tr
                                    key={`${row.kind}-${row.feedback_id || row.product_name || row.feedback_tag || index}`}
                                    className={row.kind === "total" ? "bg-[#EFEFEF] font-bold" : "bg-white hover:bg-slate-50"}
                                >
                                    {visibleColumns.map((column) => {
                                        const value = cellValue(row, column);
                                        return (
                                            <td key={column} className={cellClassName(column)}>
                                                <CellContent
                                                    column={column}
                                                    row={row}
                                                    value={value}
                                                    onCountClick={onCountClick}
                                                    onTextClick={onTextClick}
                                                />
                                            </td>
                                        );
                                    })}
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>
            <Pagination
                currentPage={currentPage}
                totalPages={totalPages}
                pageSize={effectivePageSize}
                pageSizeOptions={pageSizeOptions}
                totalItems={totalItems}
                showingFrom={showingFrom}
                showingTo={showingTo}
                itemLabel={itemLabel}
                selectId={`report-${visibleColumns.join("-") || "table"}-page-size`}
                onPageChange={serverMode ? serverMode.onPageChange : setPage}
                onPageSizeChange={(size) => {
                    if (serverMode) {
                        serverMode.onPageSizeChange(size);
                        return;
                    }
                    setPageSize(size);
                    setPage(1);
                }}
            />
        </div>
    );
}

export function exportMatrixCsv(filename: string, columns: MatrixColumn[], rows: MatrixRow[]) {
    const header = columns.map((c) => COLUMN_LABELS[c]).join(",");
    const body = rows
        .map((row) =>
            columns
                .map((column) => {
                    const raw = cellValue(row, column).replaceAll('"', '""');
                    return `"${raw}"`;
                })
                .join(","),
        )
        .join("\n");
    const blob = new Blob([`${header}\n${body}`], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
}
