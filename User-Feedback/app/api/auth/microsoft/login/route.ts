import { NextResponse } from 'next/server';
import * as oidc from 'openid-client';
import { getMicrosoftClient, getRedirectUri } from '@/lib/auth/microsoft';
import { cookies } from 'next/headers';

export async function GET() {
    try {
        const config = await getMicrosoftClient();
        
        const code_verifier = oidc.randomPKCECodeVerifier();
        const code_challenge = await oidc.calculatePKCECodeChallenge(code_verifier);
        const state = oidc.randomState();
        
        const parameters: Record<string, string> = {
            redirect_uri: getRedirectUri(),
            scope: 'openid profile email',
            code_challenge,
            code_challenge_method: 'S256',
            state,
        };

        const redirectTo = oidc.buildAuthorizationUrl(config, parameters);

        const cookieJar = await cookies();
        
        // Store PKCE and state in cookies for the callback
        cookieJar.set('microsoft_auth_code_verifier', code_verifier, {
            httpOnly: true,
            secure: process.env.NODE_ENV === 'production',
            sameSite: 'lax',
            maxAge: 600, // 10 minutes
        });
        
        cookieJar.set('microsoft_auth_state', state, {
            httpOnly: true,
            secure: process.env.NODE_ENV === 'production',
            sameSite: 'lax',
            maxAge: 600,
        });

        return NextResponse.redirect(redirectTo.href);
    } catch (error) {
        console.error('Microsoft login error:', error);
        return NextResponse.redirect(new URL('/login?error=configuration', process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000'));
    }
}
