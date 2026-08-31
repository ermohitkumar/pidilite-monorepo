'use client';

import { LuSearch } from 'react-icons/lu';
import { Input } from '@/components/ui/input';

interface SearchInputProps {
    value: string;
    onChange: (value: string) => void;
    placeholder?: string;
    className?: string;
}

export function SearchInput({
    value,
    onChange,
    placeholder = 'Search...',
    className = '',
}: SearchInputProps) {
    return (
        <div className={`relative flex items-center ${className}`}>
            <LuSearch className="absolute left-3 h-4 w-4 text-text-disabled pointer-events-none z-10" />
            <Input
                type="text"
                placeholder={placeholder}
                value={value}
                onChange={(e) => onChange(e.target.value)}
                className="w-64 pl-9 bg-bg"
            />
        </div>
    );
}
