import * as React from "react";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={`flex h-9 w-full rounded border border-border bg-surface px-3 py-1 text-sm text-text placeholder:text-text-disabled transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand focus-visible:border-brand disabled:cursor-not-allowed disabled:opacity-50 ${className ?? ""}`}
        ref={ref}
        {...props}
      />
    );
  }
);
Input.displayName = "Input";

export { Input };
