"use client";

import * as React from "react";
import { LuCheck, LuChevronDown } from "react-icons/lu";

export interface MultiSelectProps {
    values: string[];
    onChange: (values: string[]) => void;
    options: string[];
    /** Shown when nothing is selected; an empty selection means no filter. */
    placeholder?: string;
    className?: string;
}

export function MultiSelect({ values, onChange, options, placeholder = "All", className = "" }: MultiSelectProps) {
    const [isOpen, setIsOpen] = React.useState(false);
    const containerRef = React.useRef<HTMLDivElement>(null);

    React.useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                setIsOpen(false);
            }
        };
        document.addEventListener("mousedown", handleClickOutside);
        return () => document.removeEventListener("mousedown", handleClickOutside);
    }, []);

    const selected = new Set(values);
    // Keep picked values visible even if the linked options no longer list them.
    const allOptions = [...values.filter((value) => !options.includes(value)), ...options];
    const toggle = (option: string) =>
        onChange(selected.has(option) ? values.filter((value) => value !== option) : [...values, option]);

    let label = placeholder;
    if (values.length === 1) label = values[0];
    else if (values.length > 1) label = `${values.length} selected`;

    return (
        <div className={`relative ${className}`} ref={containerRef}>
            <button
                type="button"
                title={values.join(", ") || undefined}
                className="flex h-9 w-full items-center justify-between rounded border border-border bg-surface px-3 py-1 text-sm text-text transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand focus-visible:border-brand"
                onClick={() => setIsOpen(!isOpen)}
            >
                <span className="truncate normal-case tracking-normal font-normal">{label}</span>
                <LuChevronDown className="h-4 w-4 opacity-50 ml-2 shrink-0" />
            </button>

            {isOpen && (
                <div className="absolute z-50 mt-1 max-h-60 w-full min-w-[12rem] overflow-auto rounded-md border border-border bg-surface shadow-md py-1 normal-case tracking-normal font-normal">
                    {values.length > 0 && (
                        <button
                            type="button"
                            className="flex w-full items-center px-3 py-2 text-xs font-medium text-brand hover:bg-surface-raised"
                            onClick={() => onChange([])}
                        >
                            Clear selection
                        </button>
                    )}
                    {allOptions.length === 0 ? (
                        <div className="px-3 py-2 text-sm text-text-disabled">No options</div>
                    ) : (
                        allOptions.map((option) => (
                            <button
                                key={option}
                                type="button"
                                className={`flex w-full items-center px-3 py-2 text-sm transition-colors hover:bg-surface-raised cursor-pointer ${
                                    selected.has(option) ? "text-brand font-medium" : "text-text"
                                }`}
                                onClick={() => toggle(option)}
                            >
                                <span
                                    className={`mr-2 flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
                                        selected.has(option) ? "border-brand bg-brand text-white" : "border-border"
                                    }`}
                                >
                                    {selected.has(option) && <LuCheck className="h-3 w-3" />}
                                </span>
                                <span className="flex-1 text-left truncate">{option}</span>
                            </button>
                        ))
                    )}
                </div>
            )}
        </div>
    );
}
