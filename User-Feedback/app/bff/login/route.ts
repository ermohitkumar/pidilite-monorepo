import { getBackendApiUrl } from '@/lib/auth/env';
import { SESSION_COOKIE, createSessionCookie } from '@/lib/auth/session';
import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';

export const COOKIE_OPTS = {
    httpOnly: false,
    sameSite: 'lax' as const,
    path: '/',
    maxAge: 1000 * 60 * 60 * 24, // 1day
    secure: process.env.NODE_ENV === 'production',
};

type BackendLoginErrorJson = {
    detail?: string | string[];
    message?: string;
};

function parseBackendLoginError(json: unknown, fallback: string): string {
    if (!json || typeof json !== 'object') return fallback;
    const o = json as BackendLoginErrorJson;
    if (typeof o.detail === 'string') return o.detail;
    if (Array.isArray(o.detail) && o.detail[0]) return String(o.detail[0]);
    if (typeof o.message === 'string') return o.message;
    return fallback;
}

/** Proxies to FastAPI `POST /api/v1/auth/login`. */
export async function POST(request: NextRequest) {
    let body: { email?: string; password?: string };
    try {
        body = await request.json();
    } catch {
        return NextResponse.json({ error: 'Invalid request body' }, { status: 400 });
    }

    const email = body.email?.trim();
    const password = body.password;
    if (!email || !password) {
        return NextResponse.json({ error: 'Email and password are required' }, { status: 400 });
    }

    const backendUrl = getBackendApiUrl();
    let res: Response;
    try {
        res = await fetch(`${backendUrl}/api/v1/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email: email, password: password }),
        });
    } catch (e) {
        console.error('[auth/login POST]', e);
        return NextResponse.json(
            { error: 'Could not reach the API. Check BACKEND_API_URL and that the backend is running.' },
            { status: 503 },
        );
    }

    const raw = await res.text();
    let json: unknown;
    try {
        json = raw ? JSON.parse(raw) : null;
    } catch {
        json = null;
    }

    if (!res.ok || !(json as any)?.success) {
        const msg = parseBackendLoginError(json, 'Invalid credentials');
        return NextResponse.json({ error: msg }, { status: res.status >= 400 && res.status < 500 ? res.status : 401 });
    }

    const userData = (json as any)?.data?.user;
    if (!userData?.user_id || !userData?.username || !userData?.email) {
        return NextResponse.json({ error: 'Unexpected response from the API' }, { status: 502 });
    }

    try {
        const sessionToken = await createSessionCookie({
            userId: String(userData.user_id),
            name: String(userData.username),
            email: String(userData.email),
            role: String(userData.role),
        });

        const out = NextResponse.json({ ok: true as const, user: userData });
        out.cookies.set(SESSION_COOKIE, sessionToken, COOKIE_OPTS);
        return out;
    } catch (e) {
        console.error('[auth/login POST] session', e);
        return NextResponse.json({ error: 'Server configuration error' }, { status: 500 });
    }
}
