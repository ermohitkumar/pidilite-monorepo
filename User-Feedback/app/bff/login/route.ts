import { getBackendApiUrl } from '@/lib/auth/env';
import { SESSION_COOKIE, createSessionCookie } from '@/lib/auth/session';
import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';

export const COOKIE_OPTS = {
    httpOnly: false,
    sameSite: 'lax' as const,
    path: '/',
    maxAge: 60 * 60 * 24, // 1 day, in seconds
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

function loginRedirect(request: NextRequest, error?: string) {
    const url = new URL('/login', request.url);
    if (error) url.searchParams.set('error', error);
    return NextResponse.redirect(url, 303);
}

/** Proxies to FastAPI `POST /api/v1/auth/login`. Accepts JSON from the page and a normal form post. */
export async function POST(request: NextRequest) {
    const contentType = request.headers.get('content-type') || '';
    const asJson = contentType.includes('application/json');
    let email = '';
    let password = '';

    try {
        if (asJson) {
            const body = await request.json() as { email?: string; password?: string };
            email = body.email?.trim() || '';
            password = body.password || '';
        } else {
            const form = await request.formData();
            email = String(form.get('email') || '').trim();
            password = String(form.get('password') || '');
        }
    } catch {
        if (!asJson) return loginRedirect(request, 'missing_credentials');
        return NextResponse.json({ error: 'Invalid request body' }, { status: 400 });
    }

    if (!email || !password) {
        if (!asJson) return loginRedirect(request, 'missing_credentials');
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
        if (!asJson) return loginRedirect(request, 'callback_failed');
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
        if (!asJson) return loginRedirect(request, 'invalid_credentials');
        return NextResponse.json({ error: msg }, { status: res.status >= 400 && res.status < 500 ? res.status : 401 });
    }

    const userData = (json as any)?.data?.user;
    if (!userData?.user_id || !userData?.username || !userData?.email) {
        if (!asJson) return loginRedirect(request, 'callback_failed');
        return NextResponse.json({ error: 'Unexpected response from the API' }, { status: 502 });
    }

    try {
        const sessionToken = await createSessionCookie({
            userId: String(userData.user_id),
            name: String(userData.username),
            email: String(userData.email),
            role: String(userData.role),
        });

        const out = asJson
            ? NextResponse.json({ ok: true as const, user: userData })
            : NextResponse.redirect(new URL('/', request.url), 303);
        out.cookies.set(SESSION_COOKIE, sessionToken, COOKIE_OPTS);
        return out;
    } catch (e) {
        console.error('[auth/login POST] session', e);
        if (!asJson) return loginRedirect(request, 'callback_failed');
        return NextResponse.json({ error: 'Server configuration error' }, { status: 500 });
    }
}
