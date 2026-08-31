"use client";

import React, { useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { FiArrowLeft, FiMail, FiCheckCircle } from "react-icons/fi";
import { Button } from "@/components/ui/button";

type Stage = "idle" | "submitting" | "sent" | "error";

export default function ForgotPasswordClient() {
    const [email, setEmail] = useState("");
    const [stage, setStage] = useState<Stage>("idle");
    const [errorMsg, setErrorMsg] = useState<string | null>(null);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setStage("submitting");
        setErrorMsg(null);

        try {
            // TODO: wire up to your real password-reset API
            // await fetch('/api/auth/forgot-password', { method: 'POST', body: JSON.stringify({ email }) })
            await new Promise((r) => setTimeout(r, 1000)); // simulate request
            setStage("sent");
        } catch {
            setErrorMsg("Something went wrong. Please try again.");
            setStage("error");
        }
    };

    return (
        <div className="min-h-screen flex items-center justify-center bg-bg p-6">
            <div className="w-full max-w-[440px]">
                <div className="rounded-lg border border-border bg-surface shadow-[0px_10px_30px_rgba(0,0,0,0.08)] p-8">

                    {/* Logo */}
                    <div className="flex flex-col items-center text-center space-y-2 mb-8">
                        <Image
                            src="/pidilite-seeklogo.png"
                            alt="Pidilite STT Service"
                            width={80}
                            height={80}
                            className="w-auto h-auto"
                        />
                    </div>

                    {stage === "sent" ? (
                        /* ── Success state ── */
                        <div className="flex flex-col items-center text-center space-y-4">
                            <div className="flex items-center justify-center w-14 h-14 rounded-full bg-status-green">
                                <FiCheckCircle className="w-7 h-7 text-status-green-fg" />
                            </div>
                            <div>
                                <h1 className="text-h2 text-text">Check your email</h1>
                                <p className="mt-2 text-body-md text-text-subtle">
                                    We sent a password reset link to{" "}
                                    <span className="font-medium text-text">{email}</span>.
                                    It expires in 15 minutes.
                                </p>
                            </div>
                            <p className="text-body-sm text-text-disabled">
                                Didn&apos;t receive it? Check your spam folder, or{" "}
                                <button
                                    type="button"
                                    className="text-brand hover:underline"
                                    onClick={() => setStage("idle")}
                                >
                                    try a different email
                                </button>
                                .
                            </p>
                            <Link
                                href="/login"
                                className="mt-2 inline-flex items-center gap-1.5 text-sm text-brand hover:underline"
                            >
                                <FiArrowLeft className="w-3.5 h-3.5" />
                                Back to sign in
                            </Link>
                        </div>
                    ) : (
                        /* ── Request state ── */
                        <>
                            <div className="text-center space-y-1 mb-6">
                                <h1 className="text-h2 text-text">Forgot your password?</h1>
                                <p className="text-body-md text-text-subtle">
                                    Enter your email and we&apos;ll send you a reset link.
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
                                <div className="space-y-2">
                                    <label
                                        htmlFor="email"
                                        className="block text-sm font-medium text-text-subtle"
                                    >
                                        Email address
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
                                            placeholder="you@example.com"
                                            disabled={stage === "submitting"}
                                            className="h-9 w-full rounded-md border border-border bg-surface pl-10 pr-3 text-sm text-text placeholder:text-text-disabled transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand disabled:opacity-50"
                                        />
                                    </div>
                                </div>

                                <Button
                                    type="submit"
                                    variant="primary"
                                    className="w-full"
                                    disabled={stage === "submitting"}
                                >
                                    {stage === "submitting" ? "Sending…" : "Send reset link"}
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
