"use client";

import * as React from "react";
import { LuChevronDown, LuCheck } from "react-icons/lu";

export interface SelectOption {
    label: string;
    value: string;
}

export interface SelectProps {
    value: string;
    onChange: (value: string) => void;
    options: SelectOption[];
    placeholder?: string;
    className?: string;
}

export function Select({ value, onChange, options, placeholder = "Select...", className = "" }: SelectProps) {
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

    const selectedOption = options.find((opt) => opt.value === value);

    return (
        <div className={`relative ${className}`} ref={containerRef}>
            <button
                type="button"
                className="flex h-9 w-full items-center justify-between rounded border border-border bg-surface px-3 py-1 text-sm text-text transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand focus-visible:border-brand"
                onClick={() => setIsOpen(!isOpen)}
            >
                <span className={!selectedOption ? "text-text-disabled" : "truncate"}>
                    {selectedOption ? selectedOption.label : placeholder}
                </span>
                <LuChevronDown className="h-4 w-4 opacity-50 ml-2 shrink-0" />
            </button>

            {isOpen && (
                <div className="absolute z-50 mt-1 max-h-60 w-full overflow-auto rounded-md border border-border bg-surface shadow-md py-1">
                    {options.length === 0 ? (
                        <div className="px-3 py-2 text-sm text-text-disabled">No options</div>
                    ) : (
                        options.map((option) => (
                            <button
                                key={option.value}
                                type="button"
                                className={`flex w-full items-center px-3 py-2 text-sm transition-colors hover:bg-surface-raised cursor-pointer ${
                                    value === option.value ? "text-brand font-medium" : "text-text"
                                }`}
                                onClick={() => {
                                    onChange(option.value);
                                    setIsOpen(false);
                                }}
                            >
                                <span className="flex-1 text-left truncate">{option.label}</span>
                                {value === option.value && <LuCheck className="h-4 w-4 text-brand ml-2 shrink-0" />}
                            </button>
                        ))
                    )}
                </div>
            )}
        </div>
    );
}
