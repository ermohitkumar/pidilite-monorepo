import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';
import { jwtVerify } from 'jose';

const SESSION_COOKIE = 'pidilite_session_cookie';

export async function proxy(request: NextRequest) {
    const { pathname } = request.nextUrl;

    const isPublicPath =
        pathname === '/login' ||
        pathname.startsWith('/api/login') ||
        pathname.startsWith('/api/auth/microsoft') ||
        pathname.startsWith('/api/auth/callback') ||
        pathname.startsWith('/forgot-password') ||
        pathname.startsWith('/reset-password') ||
        pathname.startsWith('/_next') || // static files
        pathname === '/favicon.ico' ||
        pathname.endsWith('.png') ||
        pathname.endsWith('.jpg') ||
        pathname.endsWith('.svg') ||
        pathname.endsWith('.webp') ||
        (process.env.NODE_ENV !== 'production' && pathname.startsWith('/reports'));

    const token = request.cookies.get(SESSION_COOKIE)?.value;

    if (!token && !isPublicPath) {
        const loginUrl = new URL('/login', request.url);
        return NextResponse.redirect(loginUrl);
    }

    if (token) {
        try {
            // Verify token validity
            const secret = new TextEncoder().encode(process.env.AUTH_SECRET);
            await jwtVerify(token, secret);

            if (pathname === '/login') {
                return NextResponse.redirect(new URL('/reports', request.url));
            }
        } catch (e) {
            // Token is invalid
            let res = NextResponse.next();
            if (!isPublicPath) {
                res = NextResponse.redirect(new URL('/login', request.url));
            }
            res.cookies.delete(SESSION_COOKIE);
            return res;
        }
    }

    return NextResponse.next();
}

// Limit the middleware to specific paths for better performance
export const config = {
    matcher: [
        /*
         * Match all request paths except for the ones starting with:
         * - _next/static (static files)
         * - _next/image (image optimization files)
         * - favicon.ico (favicon file)
         */
        '/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)',
    ],
};
