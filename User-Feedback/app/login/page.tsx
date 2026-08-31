import { getSession } from "@/lib/auth/session";
import LoginClient from "./login-client";
import { redirect } from "next/navigation";

export default async function LoginPage({ searchParams, }: {
    searchParams: Promise<{ error?: string }>;
}) {
    const session = await getSession();
    if (session) {
        redirect('/');
    }

    const { error } = await searchParams;
    return <LoginClient error={error} />;
}