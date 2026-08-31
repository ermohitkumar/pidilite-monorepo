"use client";

import { Pagination } from '@/components/ui/Pagination';
import { SearchInput } from '@/components/ui/SearchInput';
import { StatCard } from '@/components/ui/StatCard';
import { Button } from '@/components/ui/button';
import { ConfirmationDialog } from '@/components/ui/ConfirmationDialog';
import { Select } from '@/components/ui/Select';
import { TableEmpty, TableLoading } from '@/components/ui/TableStatus';
import { useAppStore } from '@/lib/store/useAppStore';
import type { AppUser, UserRole, UserStatus } from '@/lib/api/users';
import { mapBackendUserToAppUser } from '@/lib/api/users';
import { useCreateUser, useDeleteUser, useUpdateUser, useUsers } from '@/lib/hooks/users';
import { useEffect, useState } from 'react';
import {
    LuArrowUpDown,
    LuCheck,
    LuChevronDown, LuChevronUp,
    LuEye, LuEyeOff,
    LuPencil,
    LuShieldCheck,
    LuUser,
    LuUserPlus,
    LuUsers,
    LuUserX,
    LuX
} from 'react-icons/lu';
import { toast } from 'sonner';

// ── Constants ─────────────────────────────────────────────────────────────────
const ROLE_OPTIONS: Array<{ label: string; value: UserRole | 'ALL' }> = [
    { label: 'All Roles', value: 'ALL' },
    { label: 'Admin', value: 'admin' },
    { label: 'Super Admin', value: 'super_admin' },
    { label: 'User', value: 'user' },
];

const STATUS_OPTIONS: Array<{ label: string; value: UserStatus | 'ALL' }> = [
    { label: 'All Statuses', value: 'ALL' },
    { label: 'Active', value: 'active' },
    { label: 'Inactive', value: 'inactive' },
];

const PAGE_SIZE_OPTIONS = [10, 20, 50];

// ── Sub-components ────────────────────────────────────────────────────────────

function RoleBadge({ role }: { role: UserRole }) {
    const map: Record<UserRole, { cls: string; icon: React.ReactNode; label: string }> = {
        super_admin: { cls: 'bg-[#fef9c3] text-gold-dark', icon: <LuShieldCheck className="h-3 w-3" />, label: 'Super Admin' },
        admin: { cls: 'bg-[#ede9fe] text-purple-700', icon: <LuShieldCheck className="h-3 w-3" />, label: 'Admin' },
        user: { cls: 'bg-brand-subtle text-brand', icon: <LuUser className="h-3 w-3" />, label: 'User' },
    };
    const { cls, icon, label } = map[role];
    return (
        <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-label-sm font-medium ${cls}`}>
            {icon}{label}
        </span>
    );
}

function StatusDot({ status }: { status: UserStatus }) {
    const map: Record<UserStatus, { dot: string; label: string }> = {
        active: { dot: 'bg-status-green-fg', label: 'Active' },
        inactive: { dot: 'bg-status-red-fg', label: 'Inactive' },
        pending: { dot: 'bg-status-amber-fg', label: 'Pending' },
    };
    const { dot, label } = map[status];
    return (
        <span className="inline-flex items-center gap-1.5 text-body-sm text-text-subtle">
            <span className={`h-2 w-2 rounded-full ${dot}`} />
            {label}
        </span>
    );
}

// ── Invite Modal ──────────────────────────────────────────────────────────────
function InviteModal({ onClose }: { onClose: () => void }) {
    const [name, setName] = useState('');
    const [email, setEmail] = useState('');
    const [password, setPassword] = useState('');
    const [showPassword, setShowPassword] = useState(false);
    const [role, setRole] = useState<UserRole>('user');
    const [errorMessage, setErrorMessage] = useState('');

    const createUserMutation = useCreateUser();

    const isDevelopment = process.env.NEXT_PUBLIC_NODE_ENV === 'development';

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setErrorMessage('');
        try {
            await createUserMutation.mutateAsync({
                email,
                password: isDevelopment ? password : '',
                full_name: name,
                username: email.split('@')[0],
                role,
            });
            setTimeout(onClose, 1000);
        } catch (err: any) {
            setErrorMessage(err.message || 'Failed to create user');
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
            <div
                className="relative rounded-xl border border-border bg-surface shadow-2xl p-6 mx-4"
                style={{ width: '450px', maxWidth: 'calc(100vw - 2rem)', flexShrink: 0 }}
            >
                <button onClick={onClose} className="absolute right-4 top-4 text-text-disabled hover:text-text">
                    <LuX className="h-4 w-4" />
                </button>
                <h2 className="text-h3 font-semibold text-text mb-1">Create User</h2>
                <p className="text-body-sm text-text-subtle mb-5">Add a new admin or super admin to the Pidilite platform.</p>

                {createUserMutation.isSuccess ? (
                    <div className="flex flex-col items-center gap-3 py-6">
                        <div className="flex h-12 w-12 items-center justify-center rounded-full bg-status-green">
                            <LuCheck className="h-6 w-6 text-status-green-fg" />
                        </div>
                        <p className="text-body-md font-medium text-text">User created successfully!</p>
                    </div>
                ) : (
                    <form onSubmit={handleSubmit} className="space-y-4">
                        {errorMessage && (
                            <div className="rounded-md bg-status-red/10 p-3 text-body-sm text-status-red-fg">
                                {errorMessage}
                            </div>
                        )}
                        <div>
                            <label className="block text-body-sm font-medium text-text-subtle mb-1.5">Full Name</label>
                            <input
                                required value={name} onChange={e => setName(e.target.value)}
                                placeholder="e.g. Rahul Sharma"
                                className="w-full rounded-md border border-border bg-bg px-3 py-2 text-body-sm text-text placeholder:text-text-disabled focus:outline-none focus:ring-2 focus:ring-brand/30"
                            />
                        </div>
                        <div>
                            <label className="block text-body-sm font-medium text-text-subtle mb-1.5">Email Address</label>
                            <input
                                required type="email" value={email} onChange={e => setEmail(e.target.value)}
                                placeholder="name@pidilite.com"
                                className="w-full rounded-md border border-border bg-bg px-3 py-2 text-body-sm text-text placeholder:text-text-disabled focus:outline-none focus:ring-2 focus:ring-brand/30"
                            />
                        </div>
                        {isDevelopment && (
                            <div>
                                <label className="block text-body-sm font-medium text-text-subtle mb-1.5">Password</label>
                                <div className="relative">
                                    <input
                                        required
                                        type={showPassword ? 'text' : 'password'}
                                        minLength={8}
                                        value={password}
                                        onChange={e => setPassword(e.target.value)}
                                        placeholder="••••••••"
                                        className="w-full rounded-md border border-border bg-bg pl-3 pr-10 py-2 text-body-sm text-text placeholder:text-text-disabled focus:outline-none focus:ring-2 focus:ring-brand/30"
                                    />
                                    <button
                                        type="button"
                                        onClick={() => setShowPassword(!showPassword)}
                                        className="absolute inset-y-0 right-0 flex items-center pr-3 text-text-disabled hover:text-text transition-colors focus:outline-none cursor-pointer"
                                        title={showPassword ? "Hide password" : "Show password"}
                                    >
                                        {showPassword ? <LuEyeOff className="h-4 w-4" /> : <LuEye className="h-4 w-4" />}
                                    </button>
                                </div>
                            </div>
                        )}
                        <div>
                            <label className="block text-body-sm font-medium text-text-subtle mb-1.5">Role</label>
                            <Select
                                value={role}
                                onChange={(v) => setRole(v as UserRole)}
                                options={[
                                    { label: 'Admin', value: 'admin' },
                                    { label: 'Super Admin', value: 'super_admin' },
                                    { label: 'User', value: 'user' },
                                ]}
                            />
                        </div>
                        <div className="flex gap-2 pt-1">
                            <Button type="button" variant="secondary" onClick={onClose} className="flex-1">
                                Cancel
                            </Button>
                            <Button type="submit" variant="action" disabled={createUserMutation.isPending} className="flex-1">
                                {createUserMutation.isPending ? 'Creating…' : 'Create User'}
                            </Button>
                        </div>
                    </form>
                )}
            </div>
        </div>
    );
}

import { AVAILABLE_RESOURCES, ResourceType } from '@/lib/auth/permissions';

function resourcesFromUser(raw: string[] | undefined): ResourceType[] {
    const known = new Set(AVAILABLE_RESOURCES.map((item) => item.value));
    const next = new Set<ResourceType>();
    for (const item of raw || []) {
        if (item === 'dashboard' || item === 'metrics') {
            next.add('reports');
            continue;
        }
        if (known.has(item as ResourceType)) next.add(item as ResourceType);
    }
    return [...next];
}

// ── Edit Role Modal ───────────────────────────────────────────────────────────
function EditRoleModal({ user, onClose }: { user: AppUser; onClose: () => void }) {
    const [role, setRole] = useState<UserRole>(user.role);
    const [resources, setResources] = useState<ResourceType[]>(resourcesFromUser(user.allowed_resources));
    const [errorMessage, setErrorMessage] = useState('');
    const [confirmOpen, setConfirmOpen] = useState(false);

    const updateUserMutation = useUpdateUser();

    const handleSave = async () => {
        setErrorMessage('');
        try {
            await updateUserMutation.mutateAsync({
                userId: user.user_id,
                payload: { role, allowed_resources: resources },
            });
            onClose();
        } catch (err: any) {
            setErrorMessage(err.message || 'Failed to update role');
            setConfirmOpen(false);
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
            <div
                className="relative rounded-xl border border-border bg-surface shadow-2xl p-6 mx-4"
                style={{ width: '450px', maxWidth: 'calc(100vw - 2rem)', flexShrink: 0 }}
            >
                <button onClick={onClose} className="absolute right-4 top-4 text-text-disabled hover:text-text">
                    <LuX className="h-4 w-4" />
                </button>
                <h2 className="text-h3 font-semibold text-text mb-1">Edit Role & Permissions</h2>
                <p className="text-body-sm text-text-subtle mb-4">{user.name} · {user.email}</p>
                {errorMessage && (
                    <div className="rounded-md bg-status-red/10 p-3 text-body-sm text-status-red-fg mb-4">
                        {errorMessage}
                    </div>
                )}

                <div className="mb-4">
                    <label className="block text-body-sm font-medium text-text-subtle mb-1.5">Role</label>
                    <Select
                        value={role}
                        onChange={(v) => setRole(v as UserRole)}
                        options={[
                            { label: 'Admin', value: 'admin' },
                            { label: 'Super Admin', value: 'super_admin' },
                            { label: 'User', value: 'user' },
                        ]}
                    />
                </div>

                <div className="mb-6">
                    <label className="block text-body-sm font-medium text-text-subtle mb-2">Resources</label>
                    <div className="flex flex-col gap-3">
                        {AVAILABLE_RESOURCES.map((opt) => (
                            <label key={opt.value} className="flex items-center gap-2 cursor-pointer group">
                                <input
                                    type="checkbox"
                                    name="resource"
                                    value={opt.value}
                                    checked={resources.includes(opt.value)}
                                    onChange={(e) => {
                                        if (e.target.checked) {
                                            setResources(prev => [...prev, opt.value]);
                                        } else {
                                            setResources(prev => prev.filter(r => r !== opt.value));
                                        }
                                    }}
                                    className="h-4 w-4 rounded border-border text-brand focus:ring-brand/30 cursor-pointer"
                                />
                                <span className="text-body-sm text-text group-hover:text-brand transition-colors">{opt.label}</span>
                            </label>
                        ))}
                    </div>
                </div>

                <div className="flex gap-2">
                    <Button variant="secondary" onClick={onClose} className="flex-1">
                        Cancel
                    </Button>
                    <Button variant="action" onClick={() => setConfirmOpen(true)} className="flex-1">
                        Save
                    </Button>
                </div>
            </div>
            <ConfirmationDialog
                open={confirmOpen}
                title="Update User Role"
                message={`Are you sure you want to update the role and permissions for ${user.name}?`}
                confirmLabel="Update"
                variant="action"
                isLoading={updateUserMutation.isPending}
                onConfirm={handleSave}
                onCancel={() => setConfirmOpen(false)}
            />
        </div>
    );
}

// ── Main Page ─────────────────────────────────────────────────────────────────
export default function UsersClient() {
    type SortKey = 'name' | 'email' | 'role' | 'status' | 'created_at';
    type SortDir = 'asc' | 'desc' | null;

    const currentUser = useAppStore((state) => state.user);
    const [search, setSearch] = useState('');
    const [roleFilter, setRoleFilter] = useState<UserRole | 'ALL'>('ALL');
    const [statusFilter, setStatusFilter] = useState<UserStatus | 'ALL'>('ALL');
    const [currentPage, setCurrentPage] = useState(1);
    const [pageSize, setPageSize] = useState(10);
    const [sortKey, setSortKey] = useState<SortKey | null>(null);
    const [sortDir, setSortDir] = useState<SortDir>(null);
    const [inviteOpen, setInviteOpen] = useState(false);
    const [editUser, setEditUser] = useState<AppUser | null>(null);
    const [deleteConfirmUser, setDeleteConfirmUser] = useState<string | null>(null);
    const [isMounted, setIsMounted] = useState(false);

    useEffect(() => setIsMounted(true), []);

    // React Query Hooks
    const { data: response, isLoading, isError } = useUsers();

    useEffect(() => {
        if (isError) {
            toast.error("Failed to load users data.");
        }
    }, [isError]);

    const deleteUserMutation = useDeleteUser();

    const handleSort = (key: SortKey) => {
        if (sortKey !== key) { setSortKey(key); setSortDir('asc'); }
        else if (sortDir === 'asc') setSortDir('desc');
        else { setSortKey(null); setSortDir(null); }
    };

    const SortIcon = ({ colKey }: { colKey: SortKey }) => {
        if (sortKey !== colKey) return <LuArrowUpDown className="h-3 w-3 opacity-40" />;
        if (sortDir === 'asc') return <LuChevronUp className="h-3 w-3 text-brand" />;
        return <LuChevronDown className="h-3 w-3 text-brand" />;
    };

    const rawUsers = response?.data?.items.map(mapBackendUserToAppUser) || [];
    const users = rawUsers.filter(u => u.user_id !== currentUser?.user_id);

    // Filter
    const filtered = users.filter(u => {
        if (roleFilter !== 'ALL' && u.role !== roleFilter) return false;
        if (statusFilter !== 'ALL' && u.status !== statusFilter) return false;
        const q = search.toLowerCase();
        return !q || u.name.toLowerCase().includes(q) || u.email.toLowerCase().includes(q) || u.user_id.toLowerCase().includes(q);
    });

    // Sort
    const sorted = sortKey
        ? [...filtered].sort((a, b) => {
            const valA = (a[sortKey] ?? '') as string;
            const valB = (b[sortKey] ?? '') as string;
            return sortDir === 'asc' ? valA.localeCompare(valB) : valB.localeCompare(valA);
        })
        : filtered;

    // Paginate
    const totalItems = sorted.length;
    const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
    const start = (currentPage - 1) * pageSize;
    const pageUsers = sorted.slice(start, start + pageSize);
    const showingFrom = totalItems === 0 ? 0 : start + 1;
    const showingTo = Math.min(start + pageSize, totalItems);

    // Stats
    const activeCount = users.filter(u => u.status === 'active').length;
    const adminCount = users.filter(u => u.role === 'admin').length;
    const superAdminCount = users.filter(u => u.role === 'super_admin').length;
    const usersCount = users.filter(u => u.role === 'user').length;

    const hasFilter = roleFilter !== 'ALL' || statusFilter !== 'ALL';

    return (
        <div className="flex h-full flex-col gap-6 p-8 bg-bg">
            {/* Header */}
            <div className="flex items-start justify-between gap-4 flex-wrap">
                <div>
                    <h1 className="text-h1 font-bold text-text">User Management</h1>
                    <p className="mt-1 text-body-md text-text-subtle">
                        Manage team members, roles, and access across the platform.
                    </p>
                </div>
                <Button
                    id="invite-user-btn"
                    variant="action"
                    onClick={() => setInviteOpen(true)}
                    className="flex items-center gap-2 shadow-sm"
                >
                    <LuUserPlus className="h-4 w-4" />
                    Create User
                </Button>
            </div>

            {/* Stat chips */}
            <div className="flex gap-4 flex-wrap">
                <StatCard
                    label="Total Accounts"
                    value={users.length}
                    icon={<LuUsers className="h-5 w-5 text-gold-dark" />}
                />
                <StatCard
                    label="Active Accounts"
                    value={activeCount}
                    icon={<LuUsers className="h-5 w-5 text-status-green-fg" />}
                />
                <StatCard
                    label="Admins"
                    value={adminCount}
                    icon={<LuUsers className="h-5 w-5 text-purple-500" />}
                />
                <StatCard
                    label="Standard Users"
                    value={usersCount}
                    icon={<LuUser className="h-5 w-5 text-brand" />}
                />
            </div>

            {/* Table Panel */}
            <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-surface overflow-hidden">

                {/* Toolbar */}
                <div className="flex items-center justify-between gap-4 border-b border-border px-5 py-3 flex-wrap">
                    <SearchInput
                        value={search}
                        placeholder="Search by name or email…"
                        onChange={(v) => { setSearch(v); setCurrentPage(1); }}
                    />
                    <div className="flex items-center gap-2">
                        {/* Role filter */}
                        <div className="w-36">
                            <Select
                                value={roleFilter}
                                onChange={(v) => { setRoleFilter(v as UserRole | 'ALL'); setCurrentPage(1); }}
                                options={ROLE_OPTIONS}
                                placeholder='All Roles'
                            />
                        </div>
                        {/* Status filter */}
                        <div className="w-36">
                            <Select
                                value={statusFilter}
                                onChange={(v) => { setStatusFilter(v as UserStatus | 'ALL'); setCurrentPage(1); }}
                                options={STATUS_OPTIONS}
                                placeholder='All Status'
                            />
                        </div>
                        {hasFilter && (
                            <button
                                onClick={() => { setRoleFilter('ALL'); setStatusFilter('ALL'); }}
                                className="flex items-center gap-1 text-body-sm text-text-disabled hover:text-brand transition-colors cursor-pointer"
                            >
                                <LuX className="h-3.5 w-3.5" />
                                Clear
                            </button>
                        )}
                    </div>
                </div>

                {/* Table */}
                <div className="app-scrollbar min-h-0 flex-1 overflow-auto">
                    <table className="w-full min-w-[900px]">
                        <thead className="sticky top-0 z-10">
                            <tr className="border-b border-border bg-bg">
                                {([
                                    { label: 'USER', key: 'name' as SortKey },
                                    { label: 'EMAIL', key: 'email' as SortKey },
                                    { label: 'ROLE', key: 'role' as SortKey },
                                    { label: 'STATUS', key: 'status' as SortKey },
                                    { label: 'ACTIONS' },
                                ] as Array<{ label: string; key?: SortKey }>).map(({ label, key }) =>
                                    key ? (
                                        <th key={label} onClick={() => handleSort(key)}
                                            className="px-5 py-3 text-left text-label-sm text-text-disabled tracking-widest whitespace-nowrap cursor-pointer select-none">
                                            <span className="inline-flex items-center gap-1.5 hover:text-text transition-colors">
                                                {label}<SortIcon colKey={key} />
                                            </span>
                                        </th>
                                    ) : (
                                        <th key={label} className="px-5 py-3 text-left text-label-sm text-text-disabled tracking-widest whitespace-nowrap">
                                            {label}
                                        </th>
                                    )
                                )}
                            </tr>
                        </thead>
                        <tbody>
                            {isLoading ? (
                                <TableLoading colSpan={5} />
                            ) : pageUsers.length === 0 ? (
                                <TableEmpty colSpan={5} message="No users match your filters." />
                            ) : pageUsers.map((user, idx) => (
                                <tr key={user.user_id}
                                    className={`border-b border-border transition-colors hover:bg-surface-raised/50 ${idx % 2 !== 0 ? 'bg-bg/40' : ''}`}>
                                    <td className="px-5 py-3.5">
                                        <div className="flex items-center gap-3">
                                            <div>
                                                <p className="text-body-sm font-medium text-text">{user.name}</p>
                                            </div>
                                        </div>
                                    </td>
                                    <td className="px-5 py-3.5 text-body-sm text-text-subtle">{user.email}</td>
                                    <td className="px-5 py-3.5"><RoleBadge role={user.role} /></td>
                                    <td className="px-5 py-3.5"><StatusDot status={user.status} /></td>
                                    <td className="px-5 py-3.5">
                                        <div className="flex items-center gap-2">
                                            <Button
                                                id={`edit-role-${user.user_id}`}
                                                onClick={() => setEditUser(user)}
                                                title="Edit role"
                                                variant="action"
                                            >
                                                <LuPencil className="h-3.5 w-3.5" />
                                            </Button>
                                            <Button
                                                id={`deactivate-${user.user_id}`}
                                                title="Deactivate"
                                                onClick={() => setDeleteConfirmUser(user.user_id)}
                                                variant="secondary"
                                            >
                                                <LuUserX className="h-3.5 w-3.5" />
                                            </Button>
                                        </div>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>

                {/* Pagination */}
                <Pagination
                    currentPage={currentPage}
                    totalPages={totalPages}
                    pageSize={pageSize}
                    pageSizeOptions={PAGE_SIZE_OPTIONS}
                    totalItems={totalItems}
                    showingFrom={showingFrom}
                    showingTo={showingTo}
                    itemLabel="users"
                    selectId="users-page-size"
                    onPageChange={setCurrentPage}
                    onPageSizeChange={(size) => { setPageSize(size); setCurrentPage(1); }}
                />
            </div>

            {/* Modals */}
            {inviteOpen && <InviteModal onClose={() => setInviteOpen(false)} />}
            {editUser && <EditRoleModal user={editUser} onClose={() => setEditUser(null)} />}
            <ConfirmationDialog
                open={!!deleteConfirmUser}
                title="Deactivate User"
                message="Are you sure you want to deactivate this user?"
                confirmLabel="Deactivate"
                cancelLabel="Cancel"
                variant="danger"
                isLoading={deleteUserMutation.isPending}
                onConfirm={async () => {
                    if (!deleteConfirmUser) return;
                    try {
                        await deleteUserMutation.mutateAsync(deleteConfirmUser);
                        setDeleteConfirmUser(null);
                    } catch (err: any) {
                        toast.error(err.message || "Failed to deactivate user");
                        setDeleteConfirmUser(null);
                    }
                }}
                onCancel={() => setDeleteConfirmUser(null)}
            />
        </div>
    );
}
