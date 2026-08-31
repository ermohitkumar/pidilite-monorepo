"use client";

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useState } from 'react';
import { LuChevronDown, LuChevronRight, LuEllipsisVertical, LuPlus, LuSearch, LuTrash2, LuX, LuSlidersHorizontal } from 'react-icons/lu';
import { useKeywords, useCreateKeyword, useUpdateKeyword, useDeleteKeyword } from '@/lib/hooks/keywords';
import { useCategories, useLanguages, useAddCategory, useDeleteCategory, useAddLanguage, useDeleteLanguage } from '@/lib/hooks/registry';
import { ConfirmationDialog } from '@/components/ui/ConfirmationDialog';
import { TableEmpty, TableLoading } from '@/components/ui/TableStatus';
import { Select } from '@/components/ui/Select';
import { useEffect } from 'react';
import { toast } from 'sonner';

type Status = 'ACTIVE' | 'INACTIVE';

type Term = {
    id: string;
    canonicalTerm: string;
    language: string;
    owner: string;
    aliases: string[];
    category: string;
    status: Status;
    sttHintBoost: number;
    priority: string;
};

export default function LibraryClient() {
    const { data: keywordsRes, isLoading: keywordsLoading, isError } = useKeywords();
    const createKeywordMutation = useCreateKeyword();
    const updateKeywordMutation = useUpdateKeyword();
    const deleteKeywordMutation = useDeleteKeyword();

    useEffect(() => {
        if (isError) {
            toast.error("Failed to load keywords data.");
        }
    }, [isError]);

    const terms: Term[] = (keywordsRes?.data ?? []).map((kw: any) => ({
        id: kw.canonical_id,
        canonicalTerm: kw.canonical_term,
        language: 'en-IN',
        owner: kw.owner || 'Current User',
        aliases: kw.aliases || [],
        category: kw.category || 'Product',
        status: kw.status as Status,
        sttHintBoost: 10,
        priority: kw.priority > 0 ? 'High' : 'Medium',
    }));

    // Global Configuration state
    const { data: categoriesRes } = useCategories();
    const categories = categoriesRes?.data?.values || [];

    const { data: languagesRes } = useLanguages();
    const languages = languagesRes?.data?.values || [];

    const addCategoryMutation = useAddCategory();
    const deleteCategoryMutation = useDeleteCategory();
    const addLanguageMutation = useAddLanguage();
    const deleteLanguageMutation = useDeleteLanguage();

    // Filter state
    const [searchTerm, setSearchTerm] = useState('');
    const [statusFilter, setStatusFilter] = useState<Status | 'ALL'>('ALL');

    // Panel state
    const [isAdding, setIsAdding] = useState(false);
    const [editingTermId, setEditingTermId] = useState<string | null>(null);
    const [isConfiguring, setIsConfiguring] = useState(false);
    const [deleteConfirmOpen, setDeleteConfirmOpen] = useState(false);
    const [saveConfirmOpen, setSaveConfirmOpen] = useState(false);

    // Local array deletion state
    const [deleteCategoryIdx, setDeleteCategoryIdx] = useState<number | null>(null);
    const [deleteLanguageIdx, setDeleteLanguageIdx] = useState<number | null>(null);
    const [deleteAliasIdx, setDeleteAliasIdx] = useState<number | null>(null);

    // Accordion state
    const [categoriesExpanded, setCategoriesExpanded] = useState(true);
    const [languagesExpanded, setLanguagesExpanded] = useState(true);

    // Form state for Term
    const [canonicalTerm, setCanonicalTerm] = useState('');
    const [aliases, setAliases] = useState<string[]>(['']);
    const [category, setCategory] = useState('Product');
    const [language, setLanguage] = useState('en-IN');
    const [priority, setPriority] = useState('High');
    const [owner, setOwner] = useState('Current User');
    const [boost, setBoost] = useState(10);

    // Form state for Configuration
    const [newCategoryStr, setNewCategoryStr] = useState('');
    const [newLanguageStr, setNewLanguageStr] = useState('');

    const isPanelOpen = isAdding || editingTermId !== null || isConfiguring;

    const handleSave = async () => {
        try {
            if (isAdding) {
                await createKeywordMutation.mutateAsync({
                    canonical_id: crypto.randomUUID(),
                    canonical_term: canonicalTerm,
                    category,
                    aliases: aliases.filter(a => a.trim() !== ''),
                    priority: priority === 'High' ? 10 : 0,
                    owner,
                });
            } else if (editingTermId) {
                await updateKeywordMutation.mutateAsync({
                    canonicalId: editingTermId,
                    payload: {
                        canonical_term: canonicalTerm,
                        category,
                        aliases: aliases.filter(a => a.trim() !== ''),
                        priority: priority === 'High' ? 10 : 0,
                    },
                });
            }
            setSaveConfirmOpen(false);
            handleClosePanel();
        } catch (error) {
            console.error('Failed to save keyword:', error);
            setSaveConfirmOpen(false);
        }
    };

    const filteredTerms = terms.filter(term => {
        const matchesSearch = term.canonicalTerm.toLowerCase().includes(searchTerm.toLowerCase()) ||
            term.aliases.some(a => a.toLowerCase().includes(searchTerm.toLowerCase()));
        const matchesStatus = statusFilter === 'ALL' || term.status === statusFilter;
        return matchesSearch && matchesStatus;
    });

    const handleAddClick = () => {
        setIsAdding(true);
        setEditingTermId(null);
        setIsConfiguring(false);

        setCanonicalTerm('');
        setAliases(['']);
        setCategory(categories[0] || 'Product');
        setLanguage(languages[0] || 'en-IN');
        setPriority('High');
        setOwner('Current User');
        setBoost(10);
    };

    const handleRowClick = (term: Term) => {
        setIsAdding(false);
        setEditingTermId(term.id);
        setIsConfiguring(false);

        setCanonicalTerm(term.canonicalTerm);
        setAliases(term.aliases.length > 0 ? [...term.aliases] : ['']);
        setCategory(term.category);
        setLanguage(term.language);
        setPriority(term.priority);
        setOwner(term.owner);
        setBoost(term.sttHintBoost);
    };

    const handleClosePanel = () => {
        setIsAdding(false);
        setEditingTermId(null);
        setIsConfiguring(false);
    };

    return (
        <>
            <div className="flex h-full flex-col gap-6 p-8 bg-bg">
                {/* Header */}
                <div className="flex items-start justify-between">
                    <div>
                        <h1 className="text-h1 font-bold text-text">Vocabulary Registry</h1>
                        <p className="mt-1 text-body-md text-text-subtle">
                            Single source of truth for STT biasing and Gemini semantic grounding.
                        </p>
                    </div>
                    <button
                        onClick={() => {
                            setIsConfiguring(true);
                            setIsAdding(false);
                            setEditingTermId(null);
                        }}
                        className="flex items-center gap-2 rounded-md border border-border bg-surface px-3 py-1.5 text-sm font-medium text-text-subtle hover:bg-surface-raised transition-colors shadow-sm"
                    >
                        <LuSlidersHorizontal className="h-4 w-4" />
                        Configure
                    </button>
                </div>

                {/* Content Area */}
                <div className="flex min-h-0 flex-1 gap-6 items-start">
                    {/* Main Table Panel */}
                    <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-surface overflow-hidden shadow-sm" style={{ height: '100%' }}>
                        {/* Toolbar */}
                        <div className="flex items-center justify-between gap-4 border-b border-border px-5 py-4">
                            <div className="flex items-center gap-4">
                                <div className="relative w-64">
                                    <LuSearch className="absolute left-3 top-1/2 -translate-y-1/2 text-text-disabled h-4 w-4" />
                                    <Input
                                        placeholder="Search terms..."
                                        className="pl-9"
                                        value={searchTerm}
                                        onChange={(e) => setSearchTerm(e.target.value)}
                                    />
                                </div>
                                {/* <select
                                value={statusFilter}
                                onChange={(e) => setStatusFilter(e.target.value as Status | 'ALL')}
                                className="h-9 rounded border border-border bg-surface px-3 py-1 text-sm text-text focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand"
                            >
                                <option value="ALL">All Statuses</option>
                                <option value="PUBLISHED">Published</option>
                                <option value="REVIEW">Review</option>
                                <option value="DRAFT">Draft</option>
                            </select> */}
                            </div>
                            <Button
                                variant="primary"
                                className="gap-1.5 font-semibold"
                                onClick={handleAddClick}
                            >
                                <LuPlus className="h-4 w-4" />
                                Add Term
                            </Button>
                        </div>

                        {/* Table */}
                        <div className="app-scrollbar min-h-0 flex-1 overflow-auto">
                            <table className="w-full text-left min-w-[700px]">
                                <thead className="sticky top-0 z-10 bg-bg">
                                    <tr className="border-b border-border">
                                        {['CANONICAL TERM', 'ALIASES', 'CATEGORY', 'ACTIONS'].map((h) => (
                                            <th key={h} className="px-5 py-3 text-label-sm text-text-disabled tracking-widest whitespace-nowrap">
                                                {h}
                                            </th>
                                        ))}
                                    </tr>
                                </thead>
                                <tbody>
                                    {keywordsLoading ? (
                                        <TableLoading colSpan={4} />
                                    ) : filteredTerms.length === 0 ? (
                                        <TableEmpty colSpan={4} message="No terms match your search." />
                                    ) : filteredTerms.map((term) => {
                                        const isSelected = term.id === editingTermId;
                                        return (
                                            <tr
                                                key={term.id}
                                                onClick={() => handleRowClick(term)}
                                                className={`border-b border-border cursor-pointer transition-colors ${isSelected ? 'bg-surface-raised' : 'hover:bg-surface-raised/50'
                                                    }`}
                                            >
                                                <td className="px-5 py-4">
                                                    <div className="text-body-md font-bold text-text">{term.canonicalTerm}</div>
                                                    <div className="text-xs text-text-subtle mt-0.5">{term.language} · {term.owner}</div>
                                                </td>
                                                <td className="px-5 py-4">
                                                    <div className="flex flex-wrap gap-2">
                                                        {term.aliases.slice(0, 2).map((alias, idx) => (
                                                            <span key={idx} className="inline-flex items-center rounded bg-surface-raised px-2 py-1 text-xs font-medium text-text-subtle">
                                                                {alias}
                                                            </span>
                                                        ))}
                                                        {term.aliases.length > 2 && (
                                                            <span className="inline-flex items-center rounded bg-surface-raised px-2 py-1 text-xs font-medium text-text-subtle">
                                                                +{term.aliases.length - 2}
                                                            </span>
                                                        )}
                                                    </div>
                                                </td>
                                                <td className="px-5 py-4 text-body-sm text-text-subtle">
                                                    {term.category}
                                                </td>
                                                {/* <td className="px-5 py-4">
                                                <Badge
                                                    variant={term.status === 'PUBLISHED' ? 'success' : term.status === 'REVIEW' ? 'warning' : 'default'}
                                                    className="uppercase text-[10px] font-bold px-2 py-0.5"
                                                >
                                                    {term.status}
                                                </Badge>
                                            </td> */}
                                                <td className="px-5 py-4 w-16 text-center text-text-disabled">
                                                    <Button
                                                        variant="action"
                                                    >
                                                        Edit
                                                    </Button>
                                                </td>
                                            </tr>
                                        );
                                    })}
                                </tbody>
                            </table>
                        </div>
                    </div>

                    {/* Side Panel */}
                    {isPanelOpen && (
                        <div className="w-[380px] flex min-h-0 flex-col rounded-lg border border-border bg-surface shrink-0 shadow-sm" style={{ height: '100%' }}>
                            {/* Panel Header */}
                            <div className="flex items-center justify-between border-b border-border px-6 py-4">
                                <h2 className="text-h3 font-semibold text-text">
                                    {isConfiguring ? 'Registry Configuration' : isAdding ? 'Add New Term' : 'Edit Term'}
                                </h2>
                                <button
                                    onClick={handleClosePanel}
                                    className="text-text-subtle hover:text-text rounded-full p-1 border border-border hover:bg-surface-raised transition-colors"
                                >
                                    <LuX className="h-4 w-4" />
                                </button>
                            </div>

                            {isConfiguring ? (
                                /* Configuration Panel Content */
                                <div className="flex flex-col h-full flex-1 p-6 gap-4 min-h-0 bg-bg/30">
                                    {/* Categories Configuration */}
                                    <div className={`flex flex-col min-h-0 rounded-lg border border-border bg-surface shadow-sm overflow-hidden ${categoriesExpanded ? 'flex-1' : 'shrink-0'}`}>
                                        <button
                                            onClick={() => setCategoriesExpanded(!categoriesExpanded)}
                                            className="flex items-center justify-between w-full p-4 bg-surface hover:bg-surface-raised transition-colors cursor-pointer"
                                        >
                                            <h3 className="text-body-sm font-bold text-text">Categories</h3>
                                            <div className="text-text-subtle">
                                                {categoriesExpanded ? <LuChevronDown className="h-5 w-5" /> : <LuChevronRight className="h-5 w-5" />}
                                            </div>
                                        </button>

                                        {categoriesExpanded && (
                                            <div className="flex flex-col flex-1 min-h-0 px-4 pb-4 border-t border-border/50">
                                                <div className="app-scrollbar flex-1 overflow-y-auto space-y-2 min-h-0 mb-4 pr-2 pt-4">
                                                    {categories.map((cat, idx) => (
                                                        <div key={idx} className="flex items-center justify-between rounded-md border border-border bg-bg px-3 py-2">
                                                            <span className="text-sm text-text">{cat}</span>
                                                            <Button
                                                                onClick={() => setDeleteCategoryIdx(idx)}
                                                                variant='danger'
                                                            >
                                                                <LuTrash2 className="h-4 w-4" />
                                                            </Button>
                                                        </div>
                                                    ))}
                                                </div>
                                                <div className="flex gap-2 shrink-0">
                                                    <Input
                                                        placeholder="New category..."
                                                        value={newCategoryStr}
                                                        onChange={(e) => setNewCategoryStr(e.target.value)}
                                                        className="flex-1 bg-bg"
                                                    />
                                                    <Button
                                                        variant='action'
                                                        onClick={() => {
                                                            const trimmedCategory = newCategoryStr.trim();
                                                            const isDuplicate = categories.some(c => c.toLowerCase() === trimmedCategory.toLowerCase());
                                                            if (trimmedCategory && !isDuplicate) {
                                                                addCategoryMutation.mutateAsync(trimmedCategory)
                                                                    .then(() => setNewCategoryStr(''))
                                                                    .catch(() => toast.error('Failed to add category'));
                                                            } else if (trimmedCategory && isDuplicate) {
                                                                toast.warning(`"${trimmedCategory}" is already in the categories list.`);
                                                            }
                                                        }}
                                                        disabled={!newCategoryStr.trim() || addCategoryMutation.isPending}
                                                    >
                                                        Add
                                                    </Button>
                                                </div>
                                            </div>
                                        )}
                                    </div>

                                    {/* Languages Configuration */}
                                    <div className={`flex flex-col min-h-0 rounded-lg border border-border bg-surface shadow-sm overflow-hidden ${languagesExpanded ? 'flex-1' : 'shrink-0'}`}>
                                        <button
                                            onClick={() => setLanguagesExpanded(!languagesExpanded)}
                                            className="flex items-center justify-between w-full p-4 bg-surface hover:bg-surface-raised transition-colors cursor-pointer"
                                        >
                                            <h3 className="text-body-sm font-bold text-text">Languages</h3>
                                            <div className="text-text-subtle">
                                                {languagesExpanded ? <LuChevronDown className="h-5 w-5" /> : <LuChevronRight className="h-5 w-5" />}
                                            </div>
                                        </button>

                                        {languagesExpanded && (
                                            <div className="flex flex-col flex-1 min-h-0 px-4 pb-4 border-t border-border/50">
                                                <div className="app-scrollbar flex-1 overflow-y-auto space-y-2 min-h-0 mb-4 pr-2 pt-4">
                                                    {languages.map((lang, idx) => (
                                                        <div key={idx} className="flex items-center justify-between rounded-md border border-border bg-bg px-3 py-2">
                                                            <span className="text-sm text-text">{lang}</span>
                                                            <Button
                                                                onClick={() => setDeleteLanguageIdx(idx)}
                                                                variant='danger'
                                                            >
                                                                <LuTrash2 className="h-4 w-4" />
                                                            </Button>
                                                        </div>
                                                    ))}
                                                </div>
                                                <div className="flex gap-2 shrink-0">
                                                    <Input
                                                        placeholder="e.g. fr-FR"
                                                        value={newLanguageStr}
                                                        onChange={(e) => setNewLanguageStr(e.target.value)}
                                                        className="flex-1 bg-bg"
                                                    />
                                                    <Button
                                                        onClick={() => {
                                                            const trimmedLanguage = newLanguageStr.trim();
                                                            const isDuplicate = languages.some(l => l.toLowerCase() === trimmedLanguage.toLowerCase());
                                                            if (trimmedLanguage && !isDuplicate) {
                                                                addLanguageMutation.mutateAsync(trimmedLanguage)
                                                                    .then(() => setNewLanguageStr(''))
                                                                    .catch(() => toast.error('Failed to add language'));
                                                            } else if (trimmedLanguage && isDuplicate) {
                                                                toast.warning(`"${trimmedLanguage}" is already in the languages list.`);
                                                            }
                                                        }}
                                                        disabled={!newLanguageStr.trim() || addLanguageMutation.isPending}
                                                        variant='action'
                                                    >
                                                        Add
                                                    </Button>
                                                </div>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            ) : (
                                /* Add/Edit Term Panel Content */
                                <>
                                    <div className="app-scrollbar flex-1 overflow-y-auto p-6 space-y-6">
                                        {/* Canonical Term */}
                                        <div>
                                            <label className="block text-body-sm font-semibold text-text mb-2">Canonical Term</label>
                                            <Input
                                                placeholder="e.g. Fevicol SH"
                                                value={canonicalTerm}
                                                onChange={(e) => setCanonicalTerm(e.target.value)}
                                            />
                                        </div>

                                        {/* Aliases & Pronunciations */}
                                        <div>
                                            <label className="block text-body-sm font-semibold text-text mb-2">Aliases & Pronunciations</label>
                                            <div className="space-y-2">
                                                {aliases.map((alias, idx) => (
                                                    <div key={idx} className="flex items-center gap-2">
                                                        <Input
                                                            placeholder="e.g. Fevicol S H"
                                                            value={alias}
                                                            onChange={(e) => {
                                                                const newAliases = [...aliases];
                                                                newAliases[idx] = e.target.value;
                                                                setAliases(newAliases);
                                                            }}
                                                        />
                                                        <Button
                                                            onClick={() => setDeleteAliasIdx(idx)}
                                                            variant='danger'
                                                        >
                                                            <LuTrash2 className="h-4 w-4" />
                                                        </Button>
                                                    </div>
                                                ))}
                                            </div>
                                            <button
                                                onClick={() => setAliases([...aliases, ''])}
                                                className="mt-3 text-brand text-sm font-medium flex items-center gap-1 hover:underline"
                                            >
                                                <LuPlus className="h-4 w-4" /> Add Alias
                                            </button>
                                        </div>

                                        {/* Category & Language */}
                                        <div className="grid grid-cols-2 gap-4">
                                            <div>
                                                <label className="block text-body-sm font-semibold text-text mb-2">Category</label>
                                                <Select
                                                    value={category}
                                                    onChange={setCategory}
                                                    options={categories.map((c) => ({ label: c, value: c }))}
                                                />
                                            </div>
                                            <div>
                                                <label className="block text-body-sm font-semibold text-text mb-2">Language</label>
                                                <Select
                                                    value={language}
                                                    onChange={setLanguage}
                                                    options={languages.map((l) => ({ label: l, value: l }))}
                                                />
                                            </div>
                                        </div>

                                        {/* Priority & Owner */}
                                        {/* <div className="grid grid-cols-2 gap-4">
                                        <div>
                                            <label className="block text-body-sm font-semibold text-text mb-2">Priority</label>
                                            <select
                                                value={priority}
                                                onChange={(e) => setPriority(e.target.value)}
                                                className="w-full h-9 rounded border border-border bg-surface px-3 py-1 text-sm text-text focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-brand"
                                            >
                                                <option>High</option>
                                                <option>Medium</option>
                                                <option>Low</option>
                                            </select>
                                        </div>
                                        <div>
                                            <label className="block text-body-sm font-semibold text-text mb-2">Owner</label>
                                            <Input
                                                value={owner}
                                                onChange={(e) => setOwner(e.target.value)}
                                            />
                                        </div>
                                    </div> */}
                                    </div>

                                    {/* Panel Footer */}
                                    <div className="flex items-center justify-between border-t border-border p-5">
                                        {/* Delete — only in edit mode */}
                                        {editingTermId ? (
                                            <Button
                                                type="button"
                                                variant="danger"
                                                disabled={deleteKeywordMutation.isPending}
                                                onClick={() => setDeleteConfirmOpen(true)}
                                                className="gap-1.5"
                                            >
                                                <LuTrash2 className="h-3.5 w-3.5" />
                                                {deleteKeywordMutation.isPending ? 'Deleting…' : 'Delete'}
                                            </Button>
                                        ) : (
                                            <div />
                                        )}

                                        {/* Save / Update */}
                                        <Button
                                            variant="action"
                                            className="font-semibold"
                                            disabled={createKeywordMutation.isPending || updateKeywordMutation.isPending}
                                            onClick={() => {
                                                const trimmedTerm = canonicalTerm.trim();
                                                const isDuplicate = terms.some(t =>
                                                    t.canonicalTerm.toLowerCase() === trimmedTerm.toLowerCase() &&
                                                    t.id !== editingTermId
                                                );
                                                if (isDuplicate) {
                                                    toast.warning(`"${trimmedTerm}" already exists in the vocabulary registry.`);
                                                    return;
                                                }
                                                setSaveConfirmOpen(true);
                                            }}
                                        >
                                            {(createKeywordMutation.isPending || updateKeywordMutation.isPending)
                                                ? 'Saving…'
                                                : isAdding ? 'Save' : 'Update'}
                                        </Button>
                                    </div>
                                </>
                            )}
                        </div>
                    )}
                </div>
            </div>

            <ConfirmationDialog
                open={saveConfirmOpen}
                title={isAdding ? "Add Term" : "Update Term"}
                message={`Are you sure you want to ${isAdding ? 'add' : 'update'} "${canonicalTerm}"?`}
                confirmLabel={isAdding ? "Save" : "Update"}
                variant="action"
                isLoading={createKeywordMutation.isPending || updateKeywordMutation.isPending}
                onConfirm={handleSave}
                onCancel={() => setSaveConfirmOpen(false)}
            />
            <ConfirmationDialog
                open={deleteConfirmOpen}
                title="Delete Term"
                message={`Are you sure you want to delete "${canonicalTerm}"? This action cannot be undone.`}
                confirmLabel="Delete"
                variant="danger"
                isLoading={deleteKeywordMutation.isPending}
                onConfirm={async () => {
                    if (!editingTermId) return;
                    try {
                        await deleteKeywordMutation.mutateAsync(editingTermId);
                        setDeleteConfirmOpen(false);
                        handleClosePanel();
                    } catch (error) {
                        console.error('Failed to delete keyword:', error);
                    }
                }}
                onCancel={() => setDeleteConfirmOpen(false)}
            />

            <ConfirmationDialog
                open={deleteCategoryIdx !== null}
                title="Remove Category"
                message={`Are you sure you want to remove "${deleteCategoryIdx !== null ? categories[deleteCategoryIdx] : ''}" from your categories?`}
                confirmLabel="Remove"
                variant="danger"
                isLoading={deleteCategoryMutation.isPending}
                onConfirm={async () => {
                    if (deleteCategoryIdx !== null) {
                        try {
                            await deleteCategoryMutation.mutateAsync(categories[deleteCategoryIdx]);
                            setDeleteCategoryIdx(null);
                        } catch (error) {
                            toast.error("Failed to remove category");
                        }
                    }
                }}
                onCancel={() => setDeleteCategoryIdx(null)}
            />

            <ConfirmationDialog
                open={deleteLanguageIdx !== null}
                title="Remove Language"
                message={`Are you sure you want to remove "${deleteLanguageIdx !== null ? languages[deleteLanguageIdx] : ''}" from your languages?`}
                confirmLabel="Remove"
                variant="danger"
                isLoading={deleteLanguageMutation.isPending}
                onConfirm={async () => {
                    if (deleteLanguageIdx !== null) {
                        try {
                            await deleteLanguageMutation.mutateAsync(languages[deleteLanguageIdx]);
                            setDeleteLanguageIdx(null);
                        } catch (error) {
                            toast.error("Failed to remove language");
                        }
                    }
                }}
                onCancel={() => setDeleteLanguageIdx(null)}
            />

            <ConfirmationDialog
                open={deleteAliasIdx !== null}
                title="Remove Alias"
                message={`Are you sure you want to remove "${deleteAliasIdx !== null ? aliases[deleteAliasIdx] : ''}" from your aliases?`}
                confirmLabel="Remove"
                variant="danger"
                onConfirm={() => {
                    if (deleteAliasIdx !== null) {
                        const newAliases = aliases.filter((_, i) => i !== deleteAliasIdx);
                        setAliases(newAliases.length ? newAliases : ['']);
                        setDeleteAliasIdx(null);
                    }
                }}
                onCancel={() => setDeleteAliasIdx(null)}
            />
        </>
    );
}
