function stripTrailingSlash(url: string): string {
    return url.trim().replace(/\/$/, '');
}

function hasScheme(url: string): boolean {
    return /^https?:\/\//i.test(url);
}

/** UAT stores the internal load-balancer host with no scheme. */
function withScheme(url: string, scheme: 'http' | 'https'): string {
    const trimmed = stripTrailingSlash(url);
    if (!trimmed) return trimmed;
    if (hasScheme(trimmed)) return trimmed;
    return `${scheme}://${trimmed}`;
}

function isIpHost(host: string): boolean {
    return /^\d{1,3}(\.\d{1,3}){3}(:\d+)?$/.test(host);
}

function isLocalHost(host: string): boolean {
    const name = host.split(':')[0]?.toLowerCase() || '';
    return (
        name === 'localhost' ||
        name === '127.0.0.1' ||
        name.startsWith('192.168.') ||
        name.startsWith('10.')
    );
}

export function getAppBaseUrl(request?: { headers: Headers }): string {
    const configured = stripTrailingSlash(process.env.NEXT_PUBLIC_APP_URL || '');

    if (request) {
        const forwardedHost = request.headers.get('x-forwarded-host')?.split(',')[0]?.trim();
        const host = forwardedHost || request.headers.get('host')?.split(',')[0]?.trim() || '';
        const proto = request.headers.get('x-forwarded-proto')?.split(',')[0]?.trim()
            || (isLocalHost(host) ? 'http' : 'https');
        // Local dev often runs on a different port than NEXT_PUBLIC_APP_URL.
        if (host && isLocalHost(host)) return `${proto}://${host}`;
    }

    if (hasScheme(configured)) return configured;

    if (request) {
        const forwardedHost = request.headers.get('x-forwarded-host')?.split(',')[0]?.trim();
        const host = forwardedHost || request.headers.get('host')?.split(',')[0]?.trim() || '';
        const proto = request.headers.get('x-forwarded-proto')?.split(',')[0]?.trim() || 'https';
        if (host && !isIpHost(host)) return `${proto}://${host}`;
    }

    if (configured) return withScheme(configured, 'https');
    throw new Error('NEXT_PUBLIC_APP_URL is not defined');
}

export function getAuthSecret(): Uint8Array {
    const secret = process.env.AUTH_SECRET;
    if (!secret || secret.length < 32) {
        throw new Error('AUTH_SECRET must be set and at least 32 characters long.');
    }
    return new TextEncoder().encode(secret);
}

export function getBackendApiUrl(): string {
    const url = process.env.BACKEND_API_URL || process.env.NEXT_PUBLIC_BACKEND_API_URL;
    if (!url) {
        throw new Error('BACKEND_API_URL is not defined');
    }
    // The UAT secret is an internal IP. Server-side fetch needs a scheme,
    // and the load balancer on that IP is reached over HTTP from the VPC.
    return withScheme(url, 'http');
}

export function getMicrosoftAuthConfig() {
    const clientId = process.env.AZURE_AD_CLIENT_ID;
    const clientSecret = process.env.AZURE_AD_CLIENT_SECRET;
    const tenantId = process.env.AZURE_AD_TENANT_ID || 'common';

    if (!clientId || !clientSecret) {
        // We don't throw here to allow the app to boot without Microsoft auth configured,
        // but we'll handle it in the auth flow.
        return null;
    }

    return {
        clientId,
        clientSecret,
        tenantId,
        issuer: `https://login.microsoftonline.com/${tenantId}/v2.0`,
    };
}
