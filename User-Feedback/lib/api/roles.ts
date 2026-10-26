import { apiFetch } from './client';
import type { ResourceType } from '@/lib/auth/permissions';

export interface AppRole {
    role_id: string;
    slug: string;
    label: string;
    description: string | null;
    permissions: ResourceType[];
    is_system: boolean;
    user_count: number;
    created_at: string | null;
}

export interface RoleListResponse {
    success: boolean;
    message: string;
    data?: { items: AppRole[]; total: number };
}

export interface RoleResponse {
    success: boolean;
    message: string;
    data?: AppRole;
}

export interface RoleWritePayload {
    label?: string;
    slug?: string;
    description?: string | null;
    permissions?: string[];
}

async function apiError(res: Response, fallback: string): Promise<Error> {
    const body = await res.json().catch(() => null);
    const message = body && typeof body.message === 'string' ? body.message : fallback;
    return new Error(message || fallback);
}

export const fetchRoles = async (): Promise<RoleListResponse> => {
    const res = await apiFetch('/api/v1/roles/');
    if (!res.ok) throw await apiError(res, 'Failed to load roles');
    return res.json();
};

export const createRole = async (payload: RoleWritePayload): Promise<RoleResponse> => {
    const res = await apiFetch('/api/v1/roles/', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
    if (!res.ok) throw await apiError(res, 'Failed to create role');
    return res.json();
};

export const updateRole = async (roleId: string, payload: RoleWritePayload): Promise<RoleResponse> => {
    const res = await apiFetch(`/api/v1/roles/${roleId}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
    });
    if (!res.ok) throw await apiError(res, 'Failed to update role');
    return res.json();
};

export const deleteRole = async (roleId: string): Promise<void> => {
    const res = await apiFetch(`/api/v1/roles/${roleId}`, { method: 'DELETE' });
    if (!res.ok) throw await apiError(res, 'Failed to delete role');
};
