import * as oidc from 'openid-client';
import { getAppBaseUrl, getMicrosoftAuthConfig } from './env';

export async function getMicrosoftClient() {
    const config = getMicrosoftAuthConfig();
    if (!config) {
        throw new Error('Microsoft Auth is not configured. Check your environment variables.');
    }

    const serverMetadata = await oidc.discovery(
        new URL(config.issuer),
        config.clientId,
        config.clientSecret
    );

    return serverMetadata;
}

export function getRedirectUri() {
    return `${getAppBaseUrl()}/api/auth/callback/microsoft`;
}
