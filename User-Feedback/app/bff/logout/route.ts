import { getAppBaseUrl } from '@/lib/auth/env';
import { SESSION_COOKIE } from '@/lib/auth/session';
import { NextRequest, NextResponse } from 'next/server';
import { COOKIE_OPTS } from '../login/route';

export async function POST(request: NextRequest) {
    const base = getAppBaseUrl(request);

    // Optionally tell the backend to kill the session cookie
    try {
        const backendUrl = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_BACKEND_API_URL;
        if (backendUrl) {
            await fetch(`${backendUrl}/api/v1/auth/logout`, { method: 'POST' });
        }
    } catch (e) {
        console.error('[auth/logout] backend logout failed', e);
    }

    const res = NextResponse.redirect(new URL('/login', base), 303);
    res.cookies.set(SESSION_COOKIE, '', { ...COOKIE_OPTS, maxAge: 0 });
    return res;
}
