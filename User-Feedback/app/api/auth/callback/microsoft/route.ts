import { getAppBaseUrl } from '@/lib/auth/env';
import { getMicrosoftClient } from '@/lib/auth/microsoft';
import { createSessionCookie, SESSION_COOKIE } from '@/lib/auth/session';
import { cookies } from 'next/headers';
import { NextRequest, NextResponse } from 'next/server';
import * as oidc from 'openid-client';

export const COOKIE_OPTS = {
    httpOnly: false,
    sameSite: 'lax' as const,
    path: '/',
    maxAge: 60 * 60 * 24, // 1 day
    secure: process.env.NODE_ENV === 'production',
};

export async function GET(request: NextRequest) {
    const appBaseUrl = getAppBaseUrl();

    const cookieJar = await cookies();
    const code_verifier = cookieJar.get('microsoft_auth_code_verifier')?.value;
    const expected_state = cookieJar.get('microsoft_auth_state')?.value;

    if (!code_verifier || !expected_state) {
        return NextResponse.redirect(new URL('/login?error=missing_oauth_session', appBaseUrl));
    }

    try {
        const config = await getMicrosoftClient();

        // Reconstruct the exact callback URL using appBaseUrl to prevent mismatch errors behind reverse proxies
        const exactCurrentUrl = new URL(`/api/auth/callback/microsoft${request.nextUrl.search}`, appBaseUrl);

        const tokens = await oidc.authorizationCodeGrant(
            config,
            exactCurrentUrl,
            {
                pkceCodeVerifier: code_verifier,
                expectedState: expected_state,
            }
        );

        // Clear auth cookies
        cookieJar.delete('microsoft_auth_code_verifier');
        cookieJar.delete('microsoft_auth_state');

        // Extract user info from ID token claims
        const claims = tokens.claims();
        if (!claims) {
            throw new Error('No claims found in token');
        }

        const userId = claims.sub;
        const name = (claims.name as string) || (claims.preferred_username as string) || 'Microsoft User';
        const email = (claims.email as string) || (claims.preferred_username as string) || '';

        // In a real app, you would sync this user with your database here.
        // For now, we'll create a session based on the Microsoft info.

        const sessionToken = await createSessionCookie({
            userId: userId,
            email: email,
            name: name,
        });

        // Verify the user with the backend before allowing login
        const backendUrl = process.env.NEXT_PUBLIC_BACKEND_API_URL;
        const verifyRes = await fetch(`${backendUrl}/api/v1/auth/verify`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${sessionToken}`
            }
        });

        if (!verifyRes.ok) {
            console.error('User verification failed. Status:', verifyRes.status);
            return NextResponse.redirect(new URL('/login?error=unauthorized_user', appBaseUrl));
        }

        const verifyData = await verifyRes.json();
        const userData = verifyData?.data?.user

        // this is required for userid as the database uses a different user_id system than Microsoft
        const finalSessionData = {
            userId: userData?.user_id,
            email: userData?.email
        }

        const originalSessionToken = await createSessionCookie(finalSessionData);

        const response = NextResponse.redirect(new URL('/reports', appBaseUrl));
        response.cookies.set(SESSION_COOKIE, originalSessionToken, COOKIE_OPTS);

        return response;
    } catch (error) {
        console.error('Microsoft callback error:', error);
        return NextResponse.redirect(new URL('/login?error=callback_failed', appBaseUrl));
    }
}
