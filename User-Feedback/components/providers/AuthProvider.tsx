"use client";

import { SessionPayload } from "@/lib/auth/session";
import { useUser } from "@/lib/hooks/users";
import { useAppStore } from "@/lib/store/useAppStore";
import { ReactNode, useEffect } from "react";

export function AuthProvider({
    children,
    initialUser,
}: {
    children: ReactNode;
    initialUser: SessionPayload | null;
}) {
    const setUser = useAppStore((state) => state.setUser);
    const setIsUserLoaded = useAppStore((state) => state.setIsUserLoaded);

    const userId = initialUser?.userId ?? '';

    // TanStack Query v5: a disabled query (enabled: false) with no cached data
    // keeps isLoading = true forever because isPending stays true.
    // When there is no userId (no session cookie / logged out) we must
    // resolve the auth state immediately without waiting on the query.
    useEffect(() => {
        if (!userId) {
            setUser(null);
            setIsUserLoaded(true);
        }
    }, [userId, setUser, setIsUserLoaded]);

    const { data: user_data, isLoading } = useUser(userId);
    const user = user_data?.data;

    useEffect(() => {
        if (!userId) return; // already handled above
        if (!isLoading) {
            setUser(user ?? null);
            setIsUserLoaded(true);
        }
    }, [userId, isLoading, user, setUser, setIsUserLoaded]);

    return <>{children}</>;
}
