import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
    createKeyword,
    deleteKeyword,
    fetchKeywords,
    KeywordCreatePayload,
    KeywordUpdatePayload,
    updateKeyword,
} from '../api/keywords';

/**
 * Hook to fetch all keywords.
 */
export const useKeywords = (status?: string, category?: string) => {
    return useQuery({
        queryKey: ['keywords', { status, category }],
        queryFn: () => fetchKeywords(status, category),
    });
};

/**
 * Mutation hook to create a new keyword.
 */
export const useCreateKeyword = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (payload: KeywordCreatePayload) => createKeyword(payload),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['keywords'] });
        },
    });
};

/**
 * Mutation hook to update an existing keyword.
 */
export const useUpdateKeyword = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ canonicalId, payload }: { canonicalId: string; payload: KeywordUpdatePayload }) =>
            updateKeyword(canonicalId, payload),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['keywords'] });
        },
    });
};

/**
 * Mutation hook to soft-delete (deactivate) a keyword.
 */
export const useDeleteKeyword = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (canonicalId: string) => deleteKeyword(canonicalId),
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['keywords'] });
        },
    });
};
