import * as React from "react";

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "success" | "warning" | "error" | "brand";
  icon?: React.ReactNode;
}

const Badge = React.forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant = "default", icon, children, ...props }, ref) => {
    const base =
      "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-label-md font-semibold";

    const variants: Record<NonNullable<BadgeProps["variant"]>, string> = {
      default: "bg-surface-raised text-text-subtle border border-border",
      success: "bg-status-green text-status-green-fg border border-status-green-fg/20",
      warning: "bg-status-amber text-status-amber-fg border border-status-amber-fg/20",
      error: "bg-status-red text-status-red-fg border border-status-red-fg/20",
      brand: "bg-brand-subtle text-brand border border-brand/20",
    };

    return (
      <span
        ref={ref}
        className={`${base} ${variants[variant]} ${className ?? ""}`}
        {...props}
      >
        {icon && <span className="shrink-0 flex items-center">{icon}</span>}
        {children}
      </span>
    );
  }
);
Badge.displayName = "Badge";

export { Badge };
