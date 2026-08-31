const BASE_URL = process.env.NEXT_PUBLIC_BACKEND_API_URL || 'http://localhost:8000';

export { BASE_URL };

function getCookie(name: string): string | undefined {
    if (typeof window === 'undefined') return undefined;
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop()?.split(';').shift();
    return undefined;
}

export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
    let token: string | undefined;
    token = getCookie('pidilite_session_cookie');

    const headers = new Headers({
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
        'Authorization': `Bearer ${token}`,
        ...(init.headers as Record<string, string> | undefined),
    });

    const res = await fetch(`${BASE_URL}${path}`, {
        ...init,
        headers,
        credentials: 'include',
    });

    return res;
}
