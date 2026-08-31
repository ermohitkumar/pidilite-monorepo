import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
    CatalogProduct,
    CatalogTag,
    createProduct,
    createTag,
    deleteProduct,
    deleteTag,
    fetchProducts,
    fetchTags,
    updateProduct,
    updateTag,
} from '../api/catalog';

export const useProducts = (q?: string) =>
    useQuery({ queryKey: ['catalog', 'products', q], queryFn: () => fetchProducts(q) });

export const useCreateProduct = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload: Omit<CatalogProduct, 'id'>) => createProduct(payload),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['catalog', 'products'] }),
    });
};

export const useUpdateProduct = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, payload }: { id: string; payload: Partial<CatalogProduct> }) =>
            updateProduct(id, payload),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['catalog', 'products'] }),
    });
};

export const useDeleteProduct = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: string) => deleteProduct(id),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['catalog', 'products'] }),
    });
};

export const useTags = (q?: string) =>
    useQuery({ queryKey: ['catalog', 'tags', q], queryFn: () => fetchTags(q) });

export const useCreateTag = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload: Partial<CatalogTag>) => createTag(payload),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['catalog', 'tags'] }),
    });
};

export const useUpdateTag = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ id, payload }: { id: string | number; payload: Partial<CatalogTag> }) =>
            updateTag(id, payload),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['catalog', 'tags'] }),
    });
};

export const useDeleteTag = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (id: string | number) => deleteTag(id),
        onSuccess: () => queryClient.invalidateQueries({ queryKey: ['catalog', 'tags'] }),
    });
};
