import { apiFetch } from './client';

export interface RegistryResponseData {
    key: string;
    values: string[];
    description?: string;
    updated_at: string;
}

export interface RegistryResponse {
    success: boolean;
    message: string;
    data?: RegistryResponseData;
    error?: string | null;
    timestamp?: string;
    request_id?: string;
}

export interface RegistryItemPayload {
    value?: string;
    new_value?: string;
}

export const fetchCategories = async (): Promise<RegistryResponse> => {
    const res = await apiFetch('/api/v1/registry/categories/');
    if (!res.ok) {
        throw new Error('Failed to fetch categories');
    }
    return res.json();
};

export const addCategory = async (value: string): Promise<RegistryResponse> => {
    const res = await apiFetch('/api/v1/registry/categories/', {
        method: 'POST',
        body: JSON.stringify({ value }),
    });
    if (!res.ok) {
        throw new Error('Failed to add category');
    }
    return res.json();
};

export const updateCategory = async (oldValue: string, newValue: string): Promise<RegistryResponse> => {
    const res = await apiFetch(`/api/v1/registry/categories/${encodeURIComponent(oldValue)}`, {
        method: 'PUT',
        body: JSON.stringify({ new_value: newValue }),
    });
    if (!res.ok) {
        throw new Error(`Failed to update category ${oldValue}`);
    }
    return res.json();
};

export const deleteCategory = async (value: string): Promise<RegistryResponse> => {
    const res = await apiFetch(`/api/v1/registry/categories/${encodeURIComponent(value)}`, {
        method: 'DELETE',
    });
    if (!res.ok) {
        throw new Error(`Failed to delete category ${value}`);
    }
    return res.json();
};

export const fetchLanguages = async (): Promise<RegistryResponse> => {
    const res = await apiFetch('/api/v1/registry/languages/');
    if (!res.ok) {
        throw new Error('Failed to fetch languages');
    }
    return res.json();
};

export const addLanguage = async (value: string): Promise<RegistryResponse> => {
    const res = await apiFetch('/api/v1/registry/languages/', {
        method: 'POST',
        body: JSON.stringify({ value }),
    });
    if (!res.ok) {
        throw new Error('Failed to add language');
    }
    return res.json();
};

export const updateLanguage = async (oldValue: string, newValue: string): Promise<RegistryResponse> => {
    const res = await apiFetch(`/api/v1/registry/languages/${encodeURIComponent(oldValue)}`, {
        method: 'PUT',
        body: JSON.stringify({ new_value: newValue }),
    });
    if (!res.ok) {
        throw new Error(`Failed to update language ${oldValue}`);
    }
    return res.json();
};

export const deleteLanguage = async (value: string): Promise<RegistryResponse> => {
    const res = await apiFetch(`/api/v1/registry/languages/${encodeURIComponent(value)}`, {
        method: 'DELETE',
    });
    if (!res.ok) {
        throw new Error(`Failed to delete language ${value}`);
    }
    return res.json();
};
