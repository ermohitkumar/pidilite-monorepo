import { apiFetch } from './client';

export interface CatalogProduct {
    id: string;
    product_name: string;
    short_code?: string | null;
    description?: string | null;
    category?: string | null;
    is_active?: boolean;
}

export interface CatalogTag {
    id?: string;
    tag_id?: number;
    tag_name: string;
    sub_tag_name?: string | null;
    group_type?: string | null;
    category?: string | null;
    description?: string | null;
    is_active?: boolean;
}

export interface CatalogListResponse<T> {
    success: boolean;
    message: string;
    data?: T[];
    error?: string | null;
}

async function parseError(res: Response, fallback: string): Promise<never> {
    try {
        const body = await res.json();
        throw new Error(body.message || body.error || fallback);
    } catch (err) {
        if (err instanceof Error && err.message !== fallback) throw err;
        throw new Error(fallback);
    }
}

export async function fetchProducts(q?: string): Promise<CatalogListResponse<CatalogProduct>> {
    const qs = q ? `?q=${encodeURIComponent(q)}` : '';
    const res = await apiFetch(`/api/v1/products/${qs}`);
    if (!res.ok) await parseError(res, 'Failed to fetch products');
    return res.json();
}

export async function createProduct(payload: Omit<CatalogProduct, 'id'>): Promise<CatalogListResponse<CatalogProduct> & { data?: CatalogProduct }> {
    const res = await apiFetch('/api/v1/products/', { method: 'POST', body: JSON.stringify(payload) });
    if (!res.ok) await parseError(res, 'Failed to create product');
    return res.json();
}

export async function updateProduct(id: string, payload: Partial<CatalogProduct>) {
    const res = await apiFetch(`/api/v1/products/${id}`, { method: 'PUT', body: JSON.stringify(payload) });
    if (!res.ok) await parseError(res, 'Failed to update product');
    return res.json();
}

export async function deleteProduct(id: string) {
    const res = await apiFetch(`/api/v1/products/${id}`, { method: 'DELETE' });
    if (!res.ok) await parseError(res, 'Failed to delete product');
    return res.json();
}

export async function fetchTags(q?: string): Promise<CatalogListResponse<CatalogTag>> {
    const qs = q ? `?q=${encodeURIComponent(q)}` : '';
    const res = await apiFetch(`/api/v1/feedback-tags/${qs}`);
    if (!res.ok) await parseError(res, 'Failed to fetch tags');
    return res.json();
}

export async function createTag(payload: Partial<CatalogTag>) {
    const res = await apiFetch('/api/v1/feedback-tags/', { method: 'POST', body: JSON.stringify(payload) });
    if (!res.ok) await parseError(res, 'Failed to create tag');
    return res.json();
}

export async function updateTag(id: string | number, payload: Partial<CatalogTag>) {
    const res = await apiFetch(`/api/v1/feedback-tags/${id}`, { method: 'PUT', body: JSON.stringify(payload) });
    if (!res.ok) await parseError(res, 'Failed to update tag');
    return res.json();
}

export async function deleteTag(id: string | number) {
    const res = await apiFetch(`/api/v1/feedback-tags/${id}`, { method: 'DELETE' });
    if (!res.ok) await parseError(res, 'Failed to delete tag');
    return res.json();
}
