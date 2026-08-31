'use client';

import { LuChevronLeft, LuChevronRight } from 'react-icons/lu';

const DEFAULT_PAGE_SIZE_OPTIONS = [5, 10, 20];

interface PaginationProps {
    currentPage: number;
    totalPages: number;
    pageSize: number;
    pageSizeOptions?: number[];
    totalItems: number;
    showingFrom: number;
    showingTo: number;
    /** Singular/plural label after the count, e.g. "batches" or "files" */
    itemLabel?: string;
    /** Optional extra text appended after the count, e.g. "3 completed · 1 failed" */
    extraInfo?: string;
    /** id for the rows-per-page <select> — must be unique per page */
    selectId?: string;
    onPageChange: (page: number) => void;
    onPageSizeChange: (size: number) => void;
}

/**
 * Fixed-width pagination tokens — always produces at most 7 tokens.
 *
 * Pattern:
 *   near start  → 1  2  3  4  …  N
 *   middle      → 1  …  p-1  p  p+1  …  N
 *   near end    → 1  …  N-3  N-2  N-1  N
 */
function getPageTokens(current: number, total: number): (number | '…')[] {
    // Show all pages when total is small enough
    if (total <= 6) return Array.from({ length: total }, (_, i) => i + 1);

    // Near the start: 1 2 3 4 … N
    if (current <= 3) {
        return [1, 2, 3, 4, '…', total];
    }

    // Near the end: 1 … N-3 N-2 N-1 N
    if (current >= total - 2) {
        return [1, '…', total - 3, total - 2, total - 1, total];
    }

    // Middle: 1 … current-1 current current+1 … N
    return [1, '…', current - 1, current, current + 1, '…', total];
}

export function Pagination({
    currentPage,
    totalPages,
    pageSize,
    pageSizeOptions = DEFAULT_PAGE_SIZE_OPTIONS,
    totalItems,
    showingFrom,
    showingTo,
    itemLabel = 'items',
    extraInfo,
    selectId = 'page-size',
    onPageChange,
    onPageSizeChange,
}: PaginationProps) {
    const tokens = getPageTokens(currentPage, totalPages);

    const btnBase =
        'h-8 min-w-[32px] px-2 rounded-md border text-body-sm transition-colors disabled:opacity-40';
    const btnDefault =
        `${btnBase} border-border text-text-subtle hover:bg-surface-raised hover:text-text`;
    const btnActive =
        `${btnBase} border-brand bg-brand text-brand-fg font-semibold cursor-default`;
    const btnEllipsis =
        `${btnBase} border-transparent text-text-disabled cursor-default pointer-events-none`;

    return (
        <div className="flex items-center justify-between border-t border-border px-5 py-3 gap-4 flex-wrap">

            {/* Left — count + rows-per-page */}
            <div className="flex items-center gap-3">
                <p className="text-body-sm text-text-disabled whitespace-nowrap">
                    Showing {showingFrom}–{showingTo} of {totalItems} {itemLabel}
                    {extraInfo && ` · ${extraInfo}`}
                </p>
                <div className="flex items-center gap-2">
                    <label htmlFor={selectId} className="text-body-sm text-text-subtle whitespace-nowrap">
                        Rows per page
                    </label>
                    <select
                        id={selectId}
                        value={pageSize}
                        onChange={(e) => onPageSizeChange(Number(e.target.value))}
                        className="h-8 rounded-md border border-border bg-bg px-2 text-body-sm text-text focus:outline-none focus:ring-2 focus:ring-brand/30"
                    >
                        {pageSizeOptions.map((size) => (
                            <option key={size} value={size}>
                                {size}
                            </option>
                        ))}
                    </select>
                </div>
            </div>

            {/* Right — prev · page numbers · next */}
            <div className="flex items-center gap-1">
                {/* Previous */}
                <button
                    className={btnDefault}
                    disabled={currentPage <= 1}
                    onClick={() => onPageChange(currentPage - 1)}
                    aria-label="Previous page"
                >
                    <LuChevronLeft className="h-4 w-4 mx-auto" />
                </button>

                {/* Page tokens */}
                {tokens.map((token, i) =>
                    token === '…' ? (
                        <span key={`ellipsis-${i}`} className={btnEllipsis}>
                            …
                        </span>
                    ) : (
                        <button
                            key={token}
                            className={token === currentPage ? btnActive : btnDefault}
                            onClick={() => onPageChange(token)}
                            aria-label={`Page ${token}`}
                            aria-current={token === currentPage ? 'page' : undefined}
                        >
                            {token}
                        </button>
                    ),
                )}

                {/* Next */}
                <button
                    className={btnDefault}
                    disabled={currentPage >= totalPages}
                    onClick={() => onPageChange(currentPage + 1)}
                    aria-label="Next page"
                >
                    <LuChevronRight className="h-4 w-4 mx-auto" />
                </button>
            </div>
        </div>
    );
}
