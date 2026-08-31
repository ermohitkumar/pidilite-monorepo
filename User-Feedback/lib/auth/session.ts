import { SignJWT, jwtVerify } from 'jose';
import { cookies } from 'next/headers';
import { getAuthSecret } from './env';

export const SESSION_COOKIE = 'pidilite_session_cookie';

export type SessionPayload = {
    userId: string;
    email: string;
    name?: string;
    role?: string;
};

export async function createSessionCookie(payload: SessionPayload): Promise<string> {
    return new SignJWT({
        userId: payload.userId,
        name: payload.name,
        email: payload.email,
        role: payload.role,
    })
        .setProtectedHeader({ alg: 'HS256' })
        .setSubject(payload.userId)
        .setIssuedAt()
        .setExpirationTime('1d')
        .sign(getAuthSecret());
}

export async function verifySessionToken(token: string): Promise<SessionPayload | null> {
    try {
        const { payload } = await jwtVerify(token, getAuthSecret());
        const userId: string = typeof payload.sub === 'string' ? payload.sub : '';
        const name: string = typeof payload.name === 'string' ? payload.name : '';
        const email: string = typeof payload.email === 'string' ? payload.email : '';
        const role: string = typeof payload.role === 'string' ? payload.role : '';
        if (!userId) return null;
        return {
            userId,
            name,
            email,
            role,
        };
    } catch {
        return null;
    }
}

export async function getSession(): Promise<SessionPayload | null> {
    const jar = await cookies();
    const token = jar.get(SESSION_COOKIE)?.value;
    if (!token) return null;
    return verifySessionToken(token);
}
