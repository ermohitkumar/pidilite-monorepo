"use client";

import React, { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { FiArrowLeft, FiLock, FiEye, FiEyeOff, FiCheckCircle, FiAlertTriangle } from "react-icons/fi";
import { Button } from "@/components/ui/button";

type Stage = "idle" | "submitting" | "success" | "error";

type Props = { token?: string };

function PasswordStrength({ password }: { password: string }) {
    const checks = [
        { label: "8+ characters", pass: password.length >= 8 },
        { label: "Uppercase letter", pass: /[A-Z]/.test(password) },
        { label: "Number", pass: /[0-9]/.test(password) },
        { label: "Special character", pass: /[^A-Za-z0-9]/.test(password) },
    ];
    const score = checks.filter((c) => c.pass).length;
    const bar = [
        { threshold: 1, label: "Weak", color: "bg-status-red-fg" },
        { threshold: 2, label: "Fair", color: "bg-status-amber-fg" },
        { threshold: 3, label: "Good", color: "bg-brand" },
        { threshold: 4, label: "Strong", color: "bg-status-green-fg" },
    ];
    const level = bar.filter((b) => score >= b.threshold).pop();

    if (!password) return null;

    return (
        <div className="space-y-2 pt-1">
            {/* strength bar */}
            <div className="flex gap-1">
                {bar.map((b, i) => (
                    <div
                        key={i}
                        className={`h-1 flex-1 rounded-full transition-colors ${score >= b.threshold ? b.color : "bg-border"}`}
                    />
                ))}
            </div>
            <p className="text-label-sm text-text-disabled">
                Strength:{" "}
                <span className="font-semibold text-text-subtle">{level?.label ?? "Weak"}</span>
            </p>
            {/* checklist */}
            <ul className="grid grid-cols-2 gap-x-4 gap-y-1">
                {checks.map((c) => (
                    <li
                        key={c.label}
                        className={`flex items-center gap-1.5 text-label-sm ${c.pass ? "text-status-green-fg" : "text-text-disabled"}`}
                    >
                        <span className="text-[10px]">{c.pass ? "✓" : "○"}</span>
                        {c.label}
                    </li>
                ))}
            </ul>
        </div>
    );
}

export default function ResetPasswordClient({ token }: Props) {
    const [password, setPassword] = useState("");
    const [confirm, setConfirm] = useState("");
    const [showPassword, setShowPassword] = useState(false);
    const [showConfirm, setShowConfirm] = useState(false);
    const [stage, setStage] = useState<Stage>("idle");
    const [errorMsg, setErrorMsg] = useState<string | null>(null);

    const mismatch = confirm.length > 0 && password !== confirm;
    const isWeak = password.length > 0 && password.length < 8;
    const isReady = password.length >= 8 && password === confirm && stage !== "submitting";

    // Invalid / missing token guard
    if (!token) {
        return (
            <div className="min-h-screen flex items-center justify-center bg-bg p-6">
                <div className="w-full max-w-[440px]">
                    <div className="rounded-lg border border-border bg-surface shadow-[0px_10px_30px_rgba(0,0,0,0.08)] p-8 text-center space-y-4">
                        <div className="flex items-center justify-center w-14 h-14 rounded-full bg-status-red mx-auto">
                            <FiAlertTriangle className="w-7 h-7 text-status-red-fg" />
                        </div>
                        <h1 className="text-h2 text-text">Invalid reset link</h1>
                        <p className="text-body-md text-text-subtle">
                            This password reset link is missing or has expired.
                            Please request a new one.
                        </p>
                        <Link href="/forgot-password">
                            <Button variant="primary" className="w-full mt-2">
                                Request new link
                            </Button>
                        </Link>
                    </div>
                </div>
            </div>
        );
    }

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!isReady) return;
        setStage("submitting");
        setErrorMsg(null);

        try {
            // TODO: wire up to your real reset-password API
            // await fetch('/api/auth/reset-password', {
            //     method: 'POST',
            //     headers: { 'Content-Type': 'application/json' },
            //     body: JSON.stringify({ token, password }),
            // });
            await new Promise((r) => setTimeout(r, 1000)); // simulate request
            setStage("success");
        } catch {
            setErrorMsg("Something went wrong. Please try again or request a new link.");
            setStage("error");
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-bg p-6">
            <div className="w-full max-w-[440px]">
                <div className="rounded-lg border border-border bg-surface shadow-[0px_10px_30px_rgba(0,0,0,0.08)] p-8">

                    {/* Logo */}
                    <div className="flex justify-center mb-8">
                        <Image
                            src="/pidilite-seeklogo.png"
                            alt="Pidilite STT Service"
                            width={80}
                            height={80}
                            className="w-auto h-auto"
                        />
                    </div>

                    {stage === "success" ? (
                        /* ── Success state ── */
                        <div className="flex flex-col items-center text-center space-y-4">
                            <div className="flex items-center justify-center w-14 h-14 rounded-full bg-status-green">
                                <FiCheckCircle className="w-7 h-7 text-status-green-fg" />
                            </div>
                            <div>
                                <h1 className="text-h2 text-text">Password updated</h1>
                                <p className="mt-2 text-body-md text-text-subtle">
                                    Your password has been changed successfully. You can now sign in with your new password.
                                </p>
                            </div>
                            <Link href="/login" className="w-full mt-2">
                                <Button variant="primary" className="w-full">
                                    Go to sign in
                                </Button>
                            </Link>
                        </div>
                    ) : (
                        /* ── Form state ── */
                        <>
                            <div className="text-center space-y-1 mb-6">
                                <h1 className="text-h2 text-text">Set new password</h1>
                                <p className="text-body-md text-text-subtle">
                                    Choose a strong password for your account.
                                </p>
                            </div>

                            {errorMsg && (
                                <div
                                    className="mb-5 rounded-md border border-status-red bg-status-red px-3 py-2 text-sm text-status-red-fg"
                                    role="alert"
                                >
                                    {errorMsg}
                                </div>
                            )}

                            <form onSubmit={handleSubmit} className="space-y-5">
                                {/* New password */}
                                <div className="space-y-2">
                                    <label
                                        htmlFor="password"
                                        className="block text-sm font-medium text-text-subtle"
                                    >
                                        New password
                                    </label>
                                    <div className="relative">
                                        <FiLock
                                            className="absolute left-3 top-1/2 -translate-y-1/2 text-text-disabled"
                                            aria-hidden
                                        />
                                        <input
                                            id="password"
                                            type={showPassword ? "text" : "password"}
                                            autoComplete="new-password"
                                            required
                                            value={password}
                                            onChange={(e) => setPassword(e.target.value)}
                                            placeholder="Min. 8 characters"
                                            disabled={stage === "submitting"}
                                            className="h-9 w-full rounded-md border border-border bg-surface pl-10 pr-10 text-sm text-text placeholder:text-text-disabled transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand disabled:opacity-50"
                                        />
                                        <button
                                            type="button"
                                            onClick={() => setShowPassword((s) => !s)}
                                            className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md p-2 text-text-subtle hover:bg-surface-raised focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand"
                                            aria-label={showPassword ? "Hide password" : "Show password"}
                                        >
                                            {showPassword ? <FiEyeOff aria-hidden /> : <FiEye aria-hidden />}
                                        </button>
                                    </div>
                                    <PasswordStrength password={password} />
                                    {isWeak && (
                                        <p className="text-label-sm text-status-red-fg">
                                            Password must be at least 8 characters.
                                        </p>
                                    )}
                                </div>

                                {/* Confirm password */}
                                <div className="space-y-2">
                                    <label
                                        htmlFor="confirm"
                                        className="block text-sm font-medium text-text-subtle"
                                    >
                                        Confirm password
                                    </label>
                                    <div className="relative">
                                        <FiLock
                                            className="absolute left-3 top-1/2 -translate-y-1/2 text-text-disabled"
                                            aria-hidden
                                        />
                                        <input
                                            id="confirm"
                                            type={showConfirm ? "text" : "password"}
                                            autoComplete="new-password"
                                            required
                                            value={confirm}
                                            onChange={(e) => setConfirm(e.target.value)}
                                            placeholder="Repeat your password"
                                            disabled={stage === "submitting"}
                                            className={`h-9 w-full rounded-md border bg-surface pl-10 pr-10 text-sm text-text placeholder:text-text-disabled transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand disabled:opacity-50 ${mismatch
                                                ? "border-status-red-fg focus-visible:ring-status-red-fg"
                                                : "border-border"
                                                }`}
                                        />
                                        <button
                                            type="button"
                                            onClick={() => setShowConfirm((s) => !s)}
                                            className="absolute right-1.5 top-1/2 -translate-y-1/2 rounded-md p-2 text-text-subtle hover:bg-surface-raised focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand"
                                            aria-label={showConfirm ? "Hide password" : "Show password"}
                                        >
                                            {showConfirm ? <FiEyeOff aria-hidden /> : <FiEye aria-hidden />}
                                        </button>
                                    </div>
                                    {mismatch && (
                                        <p className="text-label-sm text-status-red-fg">
                                            Passwords do not match.
                                        </p>
                                    )}
                                </div>

                                <Button
                                    type="submit"
                                    variant="primary"
                                    className="w-full"
                                    disabled={!isReady}
                                >
                                    {stage === "submitting" ? "Updating…" : "Update password"}
                                </Button>
                            </form>

                            <div className="mt-6 text-center">
                                <Link
                                    href="/login"
                                    className="inline-flex items-center gap-1.5 text-sm text-brand hover:underline"
                                >
                                    <FiArrowLeft className="w-3.5 h-3.5" />
                                    Back to sign in
                                </Link>
                            </div>
                        </>
                    )}
                </div>
            </div>
        </div>
    );
}
