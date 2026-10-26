"use client";

import { ConfirmationDialog } from '@/components/ui/ConfirmationDialog';
import { Button } from '@/components/ui/button';
import { TableEmpty, TableLoading } from '@/components/ui/TableStatus';
import { AVAILABLE_RESOURCES, ResourceType, formatRoleLabel } from '@/lib/auth/permissions';
import type { AppRole } from '@/lib/api/roles';
import { useCreateRole, useDeleteRole, useRoles, useUpdateRole } from '@/lib/hooks/roles';
import { useEffect, useState } from 'react';
import { LuPencil, LuShield, LuTrash2, LuX } from 'react-icons/lu';
import { toast } from 'sonner';

function slugify(label: string): string {
    const slug = label
        .toLowerCase()
        .trim()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '')
        .slice(0, 50);
    if (!slug) return '';
    return /^[a-z]/.test(slug) ? slug : `role_${slug}`.slice(0, 50);
}

function RoleForm({
    initial,
    title,
    submitLabel,
    onClose,
}: {
    initial?: AppRole;
    title: string;
    submitLabel: string;
    onClose: () => void;
}) {
    const locked = initial?.slug === 'super_admin';
    const [label, setLabel] = useState(initial?.label ?? '');
    const [slug, setSlug] = useState(initial?.slug ?? '');
    const [slugEdited, setSlugEdited] = useState(Boolean(initial));
    const [description, setDescription] = useState(initial?.description ?? '');
    const [permissions, setPermissions] = useState<ResourceType[]>(
        (initial?.permissions ?? []) as ResourceType[],
    );
    const [errorMessage, setErrorMessage] = useState('');
    const createRole = useCreateRole();
    const updateRole = useUpdateRole();
    const pending = createRole.isPending || updateRole.isPending;

    const toggle = (value: ResourceType) => {
        setPermissions((current) =>
            current.includes(value) ? current.filter((item) => item !== value) : [...current, value],
        );
    };

    const handleSubmit = async (event: React.FormEvent) => {
        event.preventDefault();
        setErrorMessage('');
        try {
            if (initial) {
                await updateRole.mutateAsync({
                    roleId: initial.role_id,
                    payload: {
                        label,
                        description,
                        ...(locked ? {} : { permissions }),
                    },
                });
            } else {
                await createRole.mutateAsync({
                    label,
                    slug,
                    description,
                    permissions,
                });
            }
            onClose();
        } catch (err: unknown) {
            setErrorMessage(err instanceof Error ? err.message : 'Could not save this role');
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4">
            <div
                className="relative max-h-full overflow-y-auto rounded-xl border border-border bg-surface shadow-2xl p-6"
                style={{ width: '480px', maxWidth: '100%' }}
            >
                <button onClick={onClose} className="absolute right-4 top-4 text-text-disabled hover:text-text">
                    <LuX className="h-4 w-4" />
                </button>
                <h2 className="text-h3 font-semibold text-text mb-1">{title}</h2>
                <p className="text-body-sm text-text-subtle mb-5">
                    People with this role sign in on the login form and open the pages you select.
                </p>
                <form onSubmit={handleSubmit} className="space-y-4">
                    {errorMessage && (
                        <div className="rounded-md bg-status-red/10 p-3 text-body-sm text-status-red-fg">
                            {errorMessage}
                        </div>
                    )}
                    <div>
                        <label className="block text-body-sm font-medium text-text-subtle mb-1.5">Role name</label>
                        <input
                            required
                            value={label}
                            onChange={(event) => {
                                const next = event.target.value;
                                setLabel(next);
                                if (!slugEdited) setSlug(slugify(next));
                            }}
                            placeholder="e.g. Field Reviewer"
                            className="w-full rounded-md border border-border bg-bg px-3 py-2 text-body-sm text-text placeholder:text-text-disabled focus:outline-none focus:ring-2 focus:ring-brand/30"
                        />
                    </div>
                    {!initial && (
                        <div>
                            <label className="block text-body-sm font-medium text-text-subtle mb-1.5">Role id</label>
                            <input
                                required
                                value={slug}
                                onChange={(event) => {
                                    setSlugEdited(true);
                                    setSlug(slugify(event.target.value));
                                }}
                                placeholder="field_reviewer"
                                pattern="[a-z][a-z0-9_]*"
                                className="w-full rounded-md border border-border bg-bg px-3 py-2 text-body-sm text-text placeholder:text-text-disabled focus:outline-none focus:ring-2 focus:ring-brand/30"
                            />
                        </div>
                    )}
                    <div>
                        <label className="block text-body-sm font-medium text-text-subtle mb-1.5">Description</label>
                        <input
                            value={description}
                            onChange={(event) => setDescription(event.target.value)}
                            placeholder="What this role is for"
                            className="w-full rounded-md border border-border bg-bg px-3 py-2 text-body-sm text-text placeholder:text-text-disabled focus:outline-none focus:ring-2 focus:ring-brand/30"
                        />
                    </div>
                    <div>
                        <label className="block text-body-sm font-medium text-text-subtle mb-2">Pages</label>
                        {locked ? (
                            <p className="text-body-sm text-text-subtle">Super Admin always has full access.</p>
                        ) : (
                            <div className="flex flex-col gap-3">
                                {AVAILABLE_RESOURCES.map((option) => (
                                    <label key={option.value} className="flex items-center gap-2 cursor-pointer">
                                        <input
                                            type="checkbox"
                                            checked={permissions.includes(option.value)}
                                            onChange={() => toggle(option.value)}
                                            className="h-4 w-4 rounded border-border text-brand focus:ring-brand/30 cursor-pointer"
                                        />
                                        <span className="text-body-sm text-text">{option.label}</span>
                                    </label>
                                ))}
                            </div>
                        )}
                    </div>
                    <div className="flex gap-2 pt-1">
                        <Button type="button" variant="secondary" onClick={onClose} className="flex-1">
                            Cancel
                        </Button>
                        <Button type="submit" variant="action" disabled={pending} className="flex-1">
                            {pending ? 'Saving…' : submitLabel}
                        </Button>
                    </div>
                </form>
            </div>
        </div>
    );
}

export default function RolesPanel() {
    const { data, isLoading, isError } = useRoles();
    const deleteRole = useDeleteRole();
    const [editing, setEditing] = useState<AppRole | 'new' | null>(null);
    const [removeId, setRemoveId] = useState<string | null>(null);
    const roles = data?.data?.items ?? [];

    useEffect(() => {
        if (isError) toast.error('Failed to load roles.');
    }, [isError]);

    return (
        <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-surface overflow-hidden">
            <div className="flex items-center justify-between gap-4 border-b border-border px-5 py-3">
                <p className="text-body-sm text-text-subtle">
                    A role decides which pages an account can open after signing in.
                </p>
                <Button variant="action" onClick={() => setEditing('new')} className="flex items-center gap-2">
                    <LuShield className="h-4 w-4" />
                    Create Role
                </Button>
            </div>
            <div className="app-scrollbar min-h-0 flex-1 overflow-auto">
                <table className="w-full min-w-[760px]">
                    <thead className="sticky top-0 z-10">
                        <tr className="border-b border-border bg-bg">
                            {['ROLE', 'PAGES', 'ACCOUNTS', 'ACTIONS'].map((label) => (
                                <th key={label} className="px-5 py-3 text-left text-label-sm text-text-disabled tracking-widest whitespace-nowrap">
                                    {label}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {isLoading ? (
                            <TableLoading colSpan={4} />
                        ) : roles.length === 0 ? (
                            <TableEmpty colSpan={4} message="No roles yet." />
                        ) : roles.map((role) => {
                            const pages = role.slug === 'super_admin'
                                ? 'Full access'
                                : role.permissions
                                    .map((value) => AVAILABLE_RESOURCES.find((item) => item.value === value)?.label ?? value)
                                    .join(', ') || 'No pages';
                            return (
                                <tr key={role.role_id} className="border-b border-border hover:bg-surface-raised/50">
                                    <td className="px-5 py-3.5">
                                        <p className="text-body-sm font-medium text-text">{role.label || formatRoleLabel(role.slug)}</p>
                                        <p className="text-label-sm text-text-disabled">{role.description || role.slug}</p>
                                    </td>
                                    <td className="px-5 py-3.5 text-body-sm text-text-subtle">{pages}</td>
                                    <td className="px-5 py-3.5 text-body-sm text-text-subtle">{role.user_count}</td>
                                    <td className="px-5 py-3.5">
                                        <div className="flex items-center gap-2">
                                            <Button title="Edit role" variant="action" onClick={() => setEditing(role)}>
                                                <LuPencil className="h-3.5 w-3.5" />
                                            </Button>
                                            <Button
                                                title={role.is_system ? 'Built-in roles stay' : 'Delete role'}
                                                variant="secondary"
                                                disabled={role.is_system || role.user_count > 0}
                                                onClick={() => setRemoveId(role.role_id)}
                                            >
                                                <LuTrash2 className="h-3.5 w-3.5" />
                                            </Button>
                                        </div>
                                    </td>
                                </tr>
                            );
                        })}
                    </tbody>
                </table>
            </div>
            {editing === 'new' && (
                <RoleForm title="Create Role" submitLabel="Create Role" onClose={() => setEditing(null)} />
            )}
            {editing && editing !== 'new' && (
                <RoleForm
                    initial={editing}
                    title="Edit Role"
                    submitLabel="Save"
                    onClose={() => setEditing(null)}
                />
            )}
            <ConfirmationDialog
                open={!!removeId}
                title="Delete Role"
                message="This role will be removed. Accounts cannot be assigned to it afterwards."
                confirmLabel="Delete"
                variant="danger"
                isLoading={deleteRole.isPending}
                onConfirm={async () => {
                    if (!removeId) return;
                    try {
                        await deleteRole.mutateAsync(removeId);
                        setRemoveId(null);
                    } catch (err: unknown) {
                        toast.error(err instanceof Error ? err.message : 'Failed to delete role');
                        setRemoveId(null);
                    }
                }}
                onCancel={() => setRemoveId(null)}
            />
        </div>
    );
}
