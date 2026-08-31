"use client";

import { Button } from "@/components/ui/button";
import Image from "next/image";
import React, { useState } from "react";
import { FiEye, FiEyeOff, FiLock, FiMail } from "react-icons/fi";

function MicrosoftMark({ className }: { className?: string }) {
    return (
        <svg className={className} viewBox="0 0 23 23" aria-hidden>
            <path fill="#f25022" d="M1 1h10v10H1z" />
            <path fill="#00a4ef" d="M12 1h10v10H12z" />
            <path fill="#7fba00" d="M1 12h10v10H1z" />
            <path fill="#ffb900" d="M12 12h10v10H12z" />
        </svg>
    );
}

const ERROR_MESSAGES: Record<string, string> = {
    configuration:
        "Sign-in is not configured correctly. Please contact the administrator.",
    missing_oauth_session: "Your sign-in session expired. Please login again",
    callback_failed: "Sign-in failed. Please contact the administrator.",
    no_subject: "Please contact the administrator.",
    unauthorized_user: "You are not authorized to access this application. Please contact the administrator.",
};

type Props = { error?: string };

export default function LoginClient({ error }: Props) {
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [showPassword, setShowPassword] = useState(false);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [formError, setFormError] = useState<string | null>(null);
    const isDev = process.env.NEXT_PUBLIC_NODE_ENV === 'development';
    const urlErrorText = error
        ? (ERROR_MESSAGES[error] ?? "Sign-in failed. Please try again.")
        : null;
    const errorText = formError ?? urlErrorText;

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setFormError(null);
        setIsSubmitting(true);
        try {
            const res = await fetch('/api/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ email: email.trim(), password }),
            });
            const data = await res.json().catch(() => ({}));

            if (!res.ok || !data.ok) {
                setFormError(data.error ?? 'Sign-in failed. Check your email and password.');
                return;
            }

            window.location.href = "/reports";
        } catch {
            setFormError("Could not reach the app. Try again in a moment.");
        } finally {
            setIsSubmitting(false);
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-bg p-6">
            <div className="w-full max-w-[500px]">
                <div className="rounded-lg border border-border bg-surface shadow-[0px_10px_30px_rgba(0,0,0,0.08)] p-6">
                    <div className="flex flex-col items-center text-center space-y-2">
                        {/** LOGO HERE */}
                        <Image
                            src="/pidilite-seeklogo.png"
                            alt="Pidilite STT Service"
                            width={100}
                            height={100}
                            className="py-5 w-auto h-auto"
                        />
                        <h1 className="text-2xl font-bold">
                            Pidilite User Feedback System
                        </h1>
                        <p className="text-sm text-text-subtle">
                            Sign in to access your workspace
                        </p>
                    </div>

                    {errorText ? (
                        <div
                            className="mt-5 rounded-md border border-status-red bg-status-red px-3 py-2 text-sm text-status-red-fg"
                            role="alert"
                        >
                            {errorText}
                        </div>
                    ) : null}

                    <form onSubmit={handleSubmit} className="mt-6 space-y-5">
                        {isDev && (
                            <>
                                <div className="space-y-4">
                                    <div className="space-y-2">
                                        <label
                                            htmlFor="email"
                                            className="block text-sm font-medium text-text-subtle"
                                        >
                                            Email
                                        </label>
                                        <div className="relative">
                                            <FiMail
                                                className="absolute left-3 top-1/2 -translate-y-1/2 text-text-disabled"
                                                aria-hidden
                                            />
                                            <input
                                                id="email"
                                                type="email"
                                                autoComplete="email"
                                                required
                                                value={email}
                                                onChange={(e) => setEmail(e.target.value)}
                                                placeholder="Enter your email"
                                                className="h-9 w-full rounded-md border border-border bg-surface pl-10 pr-3 text-sm text-text placeholder:text-text-disabled transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand"
                                            />
                                        </div>
                                    </div>

                                    <div className="space-y-2">
                                        <label
                                            htmlFor="password"
                                            className="block text-sm font-medium text-text-subtle"
                                        >
                                            Password
                                        </label>
                                        <div className="relative">
                                            <FiLock
                                                className="absolute left-3 top-1/2 -translate-y-1/2 text-text-disabled"
                                                aria-hidden
                                            />
                                            <input
                                                id="password"
                                                type={showPassword ? "text" : "password"}
                                                autoComplete="current-password"
                                                required
                                                value={password}
                                                onChange={(e) => setPassword(e.target.value)}
                                                placeholder="Enter your password"
                                                className="h-9 w-full rounded-md border border-border bg-surface pl-10 pr-10 text-sm text-text placeholder:text-text-disabled transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand"
                                            />
                                            <button
                                                type="button"
                                                className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md p-2 text-text-subtle hover:bg-surface-raised focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand disabled:opacity-50"
                                                aria-label={
                                                    showPassword ? "Hide password" : "Show password"
                                                }
                                                onClick={() => setShowPassword((s) => !s)}
                                                disabled={isSubmitting}
                                            >
                                                {showPassword ? (
                                                    <FiEyeOff aria-hidden />
                                                ) : (
                                                    <FiEye aria-hidden />
                                                )}
                                            </button>
                                        </div>
                                    </div>
                                </div>

                                <div className="flex items-center justify-between gap-4">
                                    <label className="flex items-center gap-2 text-sm text-text-subtle"></label>

                                    <a
                                        href="/forgot-password"
                                        className="text-sm text-brand hover:underline"
                                    >
                                        Forgot your password?
                                    </a>
                                </div>
                            </>
                        )}

                        <div className="flex gap-2">
                            <Button
                                type="button"
                                variant="primary"
                                className="w-full"
                                disabled={isSubmitting}
                                onClick={() => {
                                    setIsSubmitting(true);
                                    window.location.href = "/api/auth/microsoft/login";
                                }}
                            >
                                <MicrosoftMark className="h-5 w-5 mr-2" />
                                {isDev ? "Sign in with Microsoft" : "Login with SSO"}
                            </Button>
                            {isDev && (
                                <Button
                                    type="submit"
                                    variant="primary"
                                    className="w-full"
                                    disabled={isSubmitting}
                                >
                                    Sign in with Email
                                </Button>
                            )}
                        </div>
                    </form>
                </div>
            </div>
        </div>
    );
}
