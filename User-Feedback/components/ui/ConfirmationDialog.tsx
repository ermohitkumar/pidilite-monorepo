"use client";

import { LuTriangleAlert, LuX } from "react-icons/lu";
import { Button, Variant } from "@/components/ui/button";

interface ConfirmationDialogProps {
    /** Whether the dialog is visible */
    open: boolean;
    /** Dialog title */
    title: string;
    /** Descriptive message shown below the title */
    message: string;
    /** Label for the confirm button (default: "Confirm") */
    confirmLabel?: string;
    /** Label for the cancel button (default: "Cancel") */
    cancelLabel?: string;
    /** Controls the confirm button colour (default: "danger") */
    variant?: Variant;
    /** Show a loading spinner + disabled state on the confirm button */
    isLoading?: boolean;
    /** Called when the user clicks confirm */
    onConfirm: () => void;
    /** Called when the user clicks cancel or the backdrop */
    onCancel: () => void;
}

const variantStyles: Record<Variant, { icon: string; iconBg: string }> = {
    action: {
        icon: "text-status-green-fg",
        iconBg: "bg-status-green",
    },
    primary: {
        icon: "text-brand-fg",
        iconBg: "bg-brand",
    },
    secondary: {
        icon: "text-text-subtle",
        iconBg: "bg-text-subtle",
    },
    danger: {
        icon: "text-status-red-fg",
        iconBg: "bg-status-red",
    },
    warning: {
        icon: "text-status-amber-fg",
        iconBg: "bg-status-amber",
    },
    info: {
        icon: "text-brand",
        iconBg: "bg-brand-subtle",
    },
};

export function ConfirmationDialog({
    open,
    title,
    message,
    confirmLabel = "Confirm",
    cancelLabel = "Cancel",
    variant = "danger",
    isLoading = false,
    onConfirm,
    onCancel,
}: ConfirmationDialogProps) {
    if (!open) return null;

    const styles = variantStyles[variant];

    return (
        <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm"
            onClick={onCancel}
        >
            <div
                className="relative w-full max-w-[450px] mx-4 rounded-xl border border-border bg-surface shadow-2xl p-6"
                onClick={(e) => e.stopPropagation()}
            >
                {/* Close button */}
                <button
                    onClick={onCancel}
                    className="absolute right-4 top-4 text-text-disabled hover:text-text transition-colors"
                    aria-label="Close"
                >
                    <LuX className="h-4 w-4" />
                </button>

                {/* Icon + Title */}
                <div className="flex items-start gap-4 mb-4">
                    <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${styles.iconBg}`}>
                        <LuTriangleAlert className={`h-5 w-5 ${styles.icon}`} />
                    </div>
                    <div>
                        <h2 className="text-h3 font-semibold text-text">{title}</h2>
                        <p className="mt-1 text-body-md text-text-subtle">{message}</p>
                    </div>
                </div>

                {/* Actions */}
                <div className="flex justify-end gap-2 mt-6">
                    <Button
                        variant="secondary"
                        onClick={onCancel}
                        disabled={isLoading}
                    >
                        {cancelLabel}
                    </Button>
                    <Button
                        variant={variant}
                        onClick={onConfirm}
                        disabled={isLoading}
                    >
                        {isLoading ? "Please wait…" : confirmLabel}
                    </Button>
                </div>
            </div>
        </div>
    );
}
