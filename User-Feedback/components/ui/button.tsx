import * as React from "react";

export type Variant = "primary" | "action" | "secondary" | "danger" | "warning" | "info";

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "primary", ...props }, ref) => {
    const base =
      "inline-flex items-center justify-center rounded text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed px-3 py-1.75 cursor-pointer";

    const variants = {
      primary: "bg-brand text-brand-fg hover:bg-brand-dark disabled:hover:bg-brand",
      action: "bg-brand text-brand-fg hover:bg-gold hover:text-text disabled:hover:bg-brand disabled:hover:text-brand-fg",
      secondary: "border border-brand bg-transparent text-brand hover:bg-brand-subtle disabled:hover:bg-transparent",
      danger: "bg-status-red-fg text-white hover:opacity-90 disabled:hover:opacity-100",
      warning: "bg-status-amber-fg text-white hover:opacity-90 disabled:hover:opacity-100",
      info: "bg-brand text-brand-fg hover:bg-brand-dark disabled:hover:bg-brand",
    };

    return (
      <button
        className={`${base} ${variants[variant]} ${className ?? ""}`}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button };
