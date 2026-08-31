export function getAppBaseUrl(): string {
    const url = process.env.NEXT_PUBLIC_APP_URL;
    if (!url) {
        throw new Error('NEXT_PUBLIC_APP_URL is not defined');
    }
    return url.replace(/\/$/, '');
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
    return url.replace(/\/$/, '');
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
