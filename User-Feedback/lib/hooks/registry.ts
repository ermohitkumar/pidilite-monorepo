import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
    addCategory,
    addLanguage,
    deleteCategory,
    deleteLanguage,
    fetchCategories,
    fetchLanguages,
    updateCategory,
    updateLanguage,
} from '../api/registry';

// --- Categories ---

export const useCategories = () => {
    return useQuery({
        queryKey: ['registry', 'categories'],
        queryFn: fetchCategories,
    });
};

export const useAddCategory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (value: string) => addCategory(value),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['registry', 'categories'] });
        },
    });
};

export const useUpdateCategory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ oldValue, newValue }: { oldValue: string; newValue: string }) =>
            updateCategory(oldValue, newValue),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['registry', 'categories'] });
        },
    });
};

export const useDeleteCategory = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (value: string) => deleteCategory(value),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['registry', 'categories'] });
        },
    });
};

// --- Languages ---

export const useLanguages = () => {
    return useQuery({
        queryKey: ['registry', 'languages'],
        queryFn: fetchLanguages,
    });
};

export const useAddLanguage = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (value: string) => addLanguage(value),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['registry', 'languages'] });
        },
    });
};

export const useUpdateLanguage = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ oldValue, newValue }: { oldValue: string; newValue: string }) =>
            updateLanguage(oldValue, newValue),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['registry', 'languages'] });
        },
    });
};

export const useDeleteLanguage = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (value: string) => deleteLanguage(value),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['registry', 'languages'] });
        },
    });
};
