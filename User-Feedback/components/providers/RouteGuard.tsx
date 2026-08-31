"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAppStore } from "@/lib/store/useAppStore";
import { getFirstAccessibleRoute, hasAccess, ROUTE_PERMISSIONS } from "@/lib/auth/permissions";
import { PageLoader } from "@/components/ui/PageLoader";

const SESSION_COOKIE = 'pidilite_session_cookie';

/** Returns true if the session cookie is still present in the browser. */
function hasSessionCookie(): boolean {
    return document.cookie.split(';').some(c => c.trim().startsWith(`${SESSION_COOKIE}=`));
}

export function RouteGuard({ children }: { children: React.ReactNode }) {
    const user = useAppStore((state) => state.user);
    const isUserLoaded = useAppStore((state) => state.isUserLoaded);
    const pathname = usePathname();
    const router = useRouter();
    const [isChecking, setIsChecking] = useState(true);
    const [isDenied, setIsDenied] = useState(false);

    /**
     * BFCache (Back-Forward Cache) handler.
     *
     * When the user logs out and presses Back, modern browsers can restore the
     * previous protected page directly from memory — bypassing the server entirely,
     * so proxy.ts never runs. The `pageshow` event fires with `event.persisted = true`
     * in this case. We check whether the session cookie still exists; if it doesn't,
     * we redirect to /login immediately.
     */
    useEffect(() => {
        const handlePageShow = (event: PageTransitionEvent) => {
            if (event.persisted && !hasSessionCookie()) {
                router.replace('/login');
            }
        };

        window.addEventListener('pageshow', handlePageShow);
        return () => window.removeEventListener('pageshow', handlePageShow);
    }, [router]);

    useEffect(() => {
        // Find if the current pathname starts with any of the defined routes in ROUTE_PERMISSIONS
        const matchingRoute = Object.keys(ROUTE_PERMISSIONS).find(route =>
            pathname === route || pathname.startsWith(`${route}/`)
        );

        if (
            process.env.NODE_ENV !== "production" &&
            (pathname === "/reports" || pathname.startsWith("/reports/"))
        ) {
            setIsChecking(false);
            setIsDenied(false);
            return;
        }

        if (matchingRoute) {
            const requiredPermission = ROUTE_PERMISSIONS[matchingRoute];

            // If the user object hasn't loaded yet, we wait.
            // If the user is loaded, check permissions.
            if (isUserLoaded) {
                // No session at all (logged out / SPA navigation to a protected route).
                // proxy.ts handles hard navigations; this handles client-side SPA navigations.
                if (!user) {
                    router.replace('/login');
                    return;
                }

                if (!hasAccess(user, requiredPermission as any)) {
                    // Authenticated but lacks access to this route.
                    const fallbackRoute = getFirstAccessibleRoute(user);

                    if (!fallbackRoute) {
                        // User has no permissions at all
                        setIsChecking(false);
                        setIsDenied(true);
                        return;
                    }

                    router.replace(fallbackRoute);
                    return;
                }
            } else {
                // User is not loaded yet, do not render children yet
                setIsChecking(true);
                return;
            }
        }

        // Allowed or public route
        setIsChecking(false);
        setIsDenied(false);

    }, [pathname, user, isUserLoaded, router]);

    if (isDenied) {
        return (
            <div className="flex h-screen w-full flex-col items-center justify-center bg-bg gap-4 p-8 text-center">
                <div className="text-h3 font-bold text-status-red-fg">Access Denied</div>
                <div className="text-body-md text-text-subtle">
                    You do not have permission to view any pages on this platform. Please contact an administrator to assign you roles and permissions.
                </div>
                <form action="/api/logout" method="post" className="mt-4">
                    <button
                        type="submit"
                        className="rounded-md border border-border bg-surface px-6 py-2 text-body-sm font-medium text-text-subtle hover:bg-surface-raised hover:text-text transition-colors shadow-sm cursor-pointer"
                        title="Log out"
                    >
                        Log out
                    </button>
                </form>
            </div>
        );
    }

    // Show nothing (or a spinner) while checking permissions to avoid flashing protected content
    if (isChecking && Object.keys(ROUTE_PERMISSIONS).some(route => pathname === route || pathname.startsWith(`${route}/`))) {
        if (!(process.env.NODE_ENV !== "production" && (pathname === "/reports" || pathname.startsWith("/reports/")))) {
            return <PageLoader fullScreen text="Verifying access..." />;
        }
    }

    return <>{children}</>;
}
