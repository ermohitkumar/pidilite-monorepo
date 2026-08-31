import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
    createUser,
    deleteUser,
    fetchUserProfile,
    fetchUsers,
    updateUser,
    UserUpdatePayload
} from '../api/users';

/**
 * Hook to fetch all users.
 */
export const useUsers = () => {
    return useQuery({
        queryKey: ['users'],
        queryFn: fetchUsers,
    });
};

/**
 * Hook to fetch a single user's profile details.
 */
export const useUser = (userId: string) => {
    return useQuery({
        queryKey: ['user', userId],
        queryFn: () => fetchUserProfile(userId),
        enabled: !!userId,
        refetchInterval: 3 * 60 * 1000,
        refetchOnWindowFocus: true,
    });
};

/**
 * Mutation hook to create a new user.
 */
export const useCreateUser = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: createUser,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['users'] });
        },
    });
};

/**
 * Mutation hook to update an existing user's details or role.
 */
export const useUpdateUser = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: ({ userId, payload }: { userId: string; payload: UserUpdatePayload }) =>
            updateUser(userId, payload),
        onSuccess: (data, variables) => {
            queryClient.invalidateQueries({ queryKey: ['users'] });
            queryClient.invalidateQueries({ queryKey: ['user', variables.userId] });
        },
    });
};

/**
 * Mutation hook to soft-delete (deactivate) a user.
 */
export const useDeleteUser = () => {
    const queryClient = useQueryClient();
    return useMutation({
        mutationFn: (userId: string) => deleteUser(userId),
        onSuccess: (data, userId) => {
            queryClient.invalidateQueries({ queryKey: ['users'] });
            queryClient.invalidateQueries({ queryKey: ['user', userId] });
        },
    });
};
