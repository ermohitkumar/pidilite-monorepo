import { apiFetch } from './client';

export type KeywordStatus = 'ACTIVE' | 'INACTIVE';

// Backend Response Schemas
export interface KeywordResponseData {
    canonical_id: string;
    canonical_term: string;
    category?: string | null;
    aliases: string[];
    priority: number;
    status: string;
    owner?: string | null;
    version: number;
    updated_at: string;
}

export interface KeywordListResponse {
    success: boolean;
    message: string;
    data?: KeywordResponseData[];
    error?: string | null;
    timestamp?: string;
    request_id?: string;
}

export interface KeywordActionResponseData {
    canonical_id: string;
    status?: string;
    version?: number;
}

export interface KeywordActionResponse {
    success: boolean;
    message: string;
    data?: KeywordActionResponseData;
    error?: string | null;
    timestamp?: string;
    request_id?: string;
}

// Backend Request Payloads
export interface KeywordCreatePayload {
    canonical_id: string;
    canonical_term: string;
    category?: string;
    aliases?: string[];
    priority?: number;
    owner?: string;
}

export interface KeywordUpdatePayload {
    canonical_term?: string;
    category?: string;
    aliases?: string[];
    priority?: number;
    status?: string;
}

/**
 * Fetch all keywords from the backend.
 * @param status Filter by status (e.g., 'ACTIVE' or 'INACTIVE')
 * @param category Filter by category
 */
export const fetchKeywords = async (status?: string, category?: string): Promise<KeywordListResponse> => {
    const params = new URLSearchParams();
    if (status) params.append('status', status);
    if (category) params.append('category', category);
    
    const queryString = params.toString() ? `?${params.toString()}` : '';
    const res = await apiFetch(`/api/v1/keywords/${queryString}`);
    
    if (!res.ok) {
        throw new Error('Failed to fetch keywords');
    }
    return res.json();
};

/**
 * Create a new keyword entry.
 */
export const createKeyword = async (payload: KeywordCreatePayload): Promise<KeywordActionResponse> => {
    const res = await apiFetch('/api/v1/keywords/', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        throw new Error('Failed to create keyword');
    }
    return res.json();
};

/**
 * Update an existing keyword's details or aliases.
 */
export const updateKeyword = async (canonicalId: string, payload: KeywordUpdatePayload): Promise<KeywordActionResponse> => {
    const res = await apiFetch(`/api/v1/keywords/${canonicalId}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        throw new Error(`Failed to update keyword ${canonicalId}`);
    }
    return res.json();
};

/**
 * Deactivate a keyword (soft delete).
 */
export const deleteKeyword = async (canonicalId: string): Promise<KeywordActionResponse> => {
    const res = await apiFetch(`/api/v1/keywords/${canonicalId}`, {
        method: 'DELETE',
    });
    if (!res.ok) {
        throw new Error(`Failed to deactivate keyword ${canonicalId}`);
    }
    return res.json();
};
