import { apiFetch } from './client';

export type UserRole = 'admin' | 'super_admin' | 'user';
export type UserStatus = 'active' | 'inactive' | 'pending';

// Type representing the shape expected by the frontend UI components
export interface AppUser {
    user_id: string;
    name: string;
    email: string;
    role: UserRole;
    status: UserStatus;
    created_at: string;
    last_login: string | null;
    allowed_resources: string[];
}

// Backend Response Schemas
export interface UserResponseData {
    user_id: string;
    email: string;
    username: string | null;
    full_name: string | null;
    role: string;
    is_active: boolean;
    allowed_resources: string[];
    created_at: string;
}

export interface UserResponse {
    success: boolean;
    message: string;
    data?: UserResponseData;
    error?: string | null;
    timestamp?: string;
    request_id?: string;
}

export interface UserListResponseData {
    items: UserResponseData[];
    total: number;
}

export interface UserListResponse {
    success: boolean;
    message: string;
    data?: UserListResponseData;
    error?: string | null;
    timestamp?: string;
    request_id?: string;
}

export interface APIResponse {
    success: boolean;
    message: string;
    data?: any;
    error?: string | null;
    timestamp?: string;
    request_id?: string;
}

// Backend Request Payloads
export interface UserCreatePayload {
    email: string;
    password: string;
    username?: string;
    full_name?: string;
    role?: string;
    allowed_resources?: string[];
}

export interface UserUpdatePayload {
    email?: string;
    password?: string;
    username?: string;
    full_name?: string;
    role?: string;
    is_active?: boolean;
    allowed_resources?: string[];
}

/**
 * Mapper helper to convert a backend UserResponseData record to the AppUser shape expected by the UI.
 */
export function mapBackendUserToAppUser(user: UserResponseData): AppUser {
    return {
        user_id: user.user_id,
        name: user.full_name || user.username || 'Unknown User',
        email: user.email,
        role: user.role as UserRole,
        status: user.is_active ? 'active' : 'inactive',
        created_at: user.created_at,
        last_login: null, // Backend does not store last login datetime
        allowed_resources: user.allowed_resources || [],
    };
}

/**
 * Fetch list of all users from the backend.
 */
export const fetchUsers = async (): Promise<UserListResponse> => {
    const res = await apiFetch('/api/v1/users/');
    if (!res.ok) {
        throw new Error('Failed to fetch users');
    }
    return res.json();
};

/**
 * Fetch a single user profile by user ID.
 */
export const fetchUserProfile = async (userId: string): Promise<UserResponse> => {
    const res = await apiFetch(`/api/v1/users/${userId}`);
    if (!res.ok) {
        throw new Error(`Failed to fetch profile for user ${userId}`);
    }
    return res.json();
};

/**
 * Create a new user (Super Admin only).
 */
export const createUser = async (payload: UserCreatePayload): Promise<UserResponse> => {
    const res = await apiFetch('/api/v1/users/', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        throw new Error('Failed to create user');
    }
    return res.json();
};

/**
 * Update an existing user's details or role (Super Admin only).
 */
export const updateUser = async (userId: string, payload: UserUpdatePayload): Promise<UserResponse> => {
    const res = await apiFetch(`/api/v1/users/${userId}`, {
        method: 'PUT',
        body: JSON.stringify(payload),
    });
    if (!res.ok) {
        throw new Error(`Failed to update user ${userId}`);
    }
    return res.json();
};

/**
 * Deactivate a user (soft delete - Super Admin only).
 */
export const deleteUser = async (userId: string): Promise<APIResponse> => {
    const res = await apiFetch(`/api/v1/users/${userId}`, {
        method: 'DELETE',
    });
    if (!res.ok) {
        throw new Error(`Failed to deactivate user ${userId}`);
    }
    return res.json();
};
