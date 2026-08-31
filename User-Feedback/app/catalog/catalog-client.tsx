"use client";

import { Button } from "@/components/ui/button";
import { ConfirmationDialog } from "@/components/ui/ConfirmationDialog";
import { Input } from "@/components/ui/input";
import { SearchInput } from "@/components/ui/SearchInput";
import { TableEmpty, TableLoading } from "@/components/ui/TableStatus";
import type { CatalogProduct, CatalogTag } from "@/lib/api/catalog";
import {
    useCreateProduct,
    useCreateTag,
    useDeleteProduct,
    useDeleteTag,
    useProducts,
    useTags,
    useUpdateProduct,
    useUpdateTag,
} from "@/lib/hooks/catalog";
import { useMemo, useState } from "react";
import { LuPackage, LuPencil, LuPlus, LuTags, LuTrash2, LuX } from "react-icons/lu";
import { toast } from "sonner";

type Tab = "products" | "tags";

function tagKey(tag: CatalogTag): string | number {
    return tag.tag_id ?? tag.id ?? tag.tag_name;
}

function ProductModal({
    product,
    onClose,
}: {
    product: CatalogProduct | null;
    onClose: () => void;
}) {
    const isEdit = Boolean(product);
    const createMutation = useCreateProduct();
    const updateMutation = useUpdateProduct();
    const [productName, setProductName] = useState(product?.product_name || "");
    const [shortCode, setShortCode] = useState(product?.short_code || "");
    const [description, setDescription] = useState(product?.description || "");
    const [isActive, setIsActive] = useState(product?.is_active !== false);
    const [error, setError] = useState("");

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        setError("");
        try {
            if (isEdit && product) {
                await updateMutation.mutateAsync({
                    id: product.id,
                    payload: {
                        product_name: productName,
                        short_code: shortCode || null,
                        description: description || null,
                        is_active: isActive,
                    },
                });
                toast.success("Product updated");
            } else {
                await createMutation.mutateAsync({
                    product_name: productName,
                    short_code: shortCode || null,
                    description: description || null,
                    is_active: isActive,
                });
                toast.success("Product created");
            }
            onClose();
        } catch (err: any) {
            setError(err.message || "Save failed");
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm">
            <form
                onSubmit={save}
                className="relative flex w-[min(32rem,calc(100vw-2rem))] shrink-0 flex-col rounded-xl border border-border bg-surface p-6 shadow-xl"
            >
                <button type="button" onClick={onClose} className="absolute right-4 top-4 text-text-disabled hover:text-text">
                    <LuX className="h-4 w-4" />
                </button>
                <h2 className="text-h3 font-semibold text-text mb-4 pr-8">{isEdit ? "Edit product" : "Add product"}</h2>
                {error && <p className="mb-3 text-body-sm text-status-red-fg">{error}</p>}
                <div className="flex min-w-0 flex-col gap-3">
                    <label className="block min-w-0 text-body-sm font-medium text-text-subtle">
                        Product name
                        <Input value={productName} onChange={(e) => setProductName(e.target.value)} required className="mt-1" />
                    </label>
                    <label className="block min-w-0 text-body-sm font-medium text-text-subtle">
                        Short code
                        <Input value={shortCode} onChange={(e) => setShortCode(e.target.value)} className="mt-1" />
                    </label>
                    <label className="block min-w-0 text-body-sm font-medium text-text-subtle">
                        Description
                        <Input value={description} onChange={(e) => setDescription(e.target.value)} className="mt-1" />
                    </label>
                    <label className="flex items-center gap-2 text-body-sm text-text">
                        <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
                        Active
                    </label>
                </div>
                <div className="mt-5 flex gap-2">
                    <Button type="button" variant="secondary" className="min-w-0 flex-1" onClick={onClose}>Cancel</Button>
                    <Button type="submit" variant="action" className="min-w-0 flex-1">Save</Button>
                </div>
            </form>
        </div>
    );
}

function TagModal({
    tag,
    onClose,
}: {
    tag: CatalogTag | null;
    onClose: () => void;
}) {
    const isEdit = Boolean(tag);
    const createMutation = useCreateTag();
    const updateMutation = useUpdateTag();
    const [tagId, setTagId] = useState(tag?.tag_id?.toString() || "");
    const [tagName, setTagName] = useState(tag?.tag_name || "");
    const [subTag, setSubTag] = useState(tag?.sub_tag_name || "");
    const [groupType, setGroupType] = useState(tag?.group_type || "PDT GROUP");
    const [category, setCategory] = useState(tag?.category || "");
    const [description, setDescription] = useState(tag?.description || "");
    const [isActive, setIsActive] = useState(tag?.is_active !== false);
    const [error, setError] = useState("");

    const id = tag?.tag_id ?? tag?.id;
    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        setError("");
        try {
            const payload = {
                tag_name: tagName,
                sub_tag_name: subTag || null,
                group_type: groupType || null,
                category: category || null,
                description: description || null,
                is_active: isActive,
            };
            if (isEdit && id != null) {
                await updateMutation.mutateAsync({ id, payload });
                toast.success("Tag updated");
            } else {
                await createMutation.mutateAsync({
                    ...payload,
                    tag_id: tagId ? Number(tagId) : undefined,
                });
                toast.success("Tag created");
            }
            onClose();
        } catch (err: any) {
            setError(err.message || "Save failed");
        }
    };

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm">
            <form
                onSubmit={save}
                className="relative flex w-[min(36rem,calc(100vw-2rem))] shrink-0 flex-col rounded-xl border border-border bg-surface p-6 shadow-xl"
            >
                <button type="button" onClick={onClose} className="absolute right-4 top-4 text-text-disabled hover:text-text">
                    <LuX className="h-4 w-4" />
                </button>
                <h2 className="text-h3 font-semibold text-text mb-4 pr-8">{isEdit ? "Edit tag" : "Add tag"}</h2>
                {error && <p className="mb-3 text-body-sm text-status-red-fg">{error}</p>}
                <div className="flex min-w-0 flex-col gap-3">
                    {!isEdit && (
                        <label className="block min-w-0 text-body-sm font-medium text-text-subtle">
                            Tag ID (optional)
                            <Input type="number" min={1} value={tagId} onChange={(e) => setTagId(e.target.value)} className="mt-1" />
                        </label>
                    )}
                    <label className="block min-w-0 text-body-sm font-medium text-text-subtle">
                        Tag name
                        <Input value={tagName} onChange={(e) => setTagName(e.target.value)} required className="mt-1" />
                    </label>
                    <label className="block min-w-0 text-body-sm font-medium text-text-subtle">
                        Sub-tag
                        <Input value={subTag} onChange={(e) => setSubTag(e.target.value)} className="mt-1" />
                    </label>
                    <label className="block min-w-0 text-body-sm font-medium text-text-subtle">
                        Group
                        <select
                            value={groupType}
                            onChange={(e) => setGroupType(e.target.value)}
                            className="mt-1 flex h-10 w-full rounded-md border border-border bg-surface px-3 py-2 text-body-sm"
                        >
                            {groupType && !["PDT GROUP", "USER GROUP", "DEALER GROUP"].includes(groupType) && (
                                <option value={groupType}>{groupType}</option>
                            )}
                            <option value="PDT GROUP">PDT GROUP</option>
                            <option value="USER GROUP">USER GROUP</option>
                            <option value="DEALER GROUP">DEALER GROUP</option>
                        </select>
                    </label>
                    <label className="block min-w-0 text-body-sm font-medium text-text-subtle">
                        Category
                        <Input value={category} onChange={(e) => setCategory(e.target.value)} className="mt-1" />
                    </label>
                    <label className="block min-w-0 text-body-sm font-medium text-text-subtle">
                        Description
                        <Input value={description} onChange={(e) => setDescription(e.target.value)} className="mt-1" />
                    </label>
                    <label className="flex items-center gap-2 text-body-sm text-text">
                        <input type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
                        Active
                    </label>
                </div>
                <div className="mt-5 flex gap-2">
                    <Button type="button" variant="secondary" className="min-w-0 flex-1" onClick={onClose}>Cancel</Button>
                    <Button type="submit" variant="action" className="min-w-0 flex-1">Save</Button>
                </div>
            </form>
        </div>
    );
}

export default function CatalogClient() {
    const [tab, setTab] = useState<Tab>("products");
    const [search, setSearch] = useState("");
    const [productModal, setProductModal] = useState<CatalogProduct | null | "new">(null);
    const [tagModal, setTagModal] = useState<CatalogTag | null | "new">(null);
    const [deleteProductId, setDeleteProductId] = useState<string | null>(null);
    const [deleteTagId, setDeleteTagId] = useState<string | number | null>(null);

    const productsQuery = useProducts();
    const tagsQuery = useTags();
    const deleteProductMutation = useDeleteProduct();
    const deleteTagMutation = useDeleteTag();

    const products = useMemo(() => {
        const rows = productsQuery.data?.data ?? [];
        const q = search.trim().toLowerCase();
        if (!q) return rows;
        return rows.filter((row) =>
            [row.product_name, row.short_code, row.description].join(" ").toLowerCase().includes(q),
        );
    }, [productsQuery.data, search]);

    const tags = useMemo(() => {
        const rows = tagsQuery.data?.data ?? [];
        const q = search.trim().toLowerCase();
        if (!q) return rows;
        return rows.filter((row) =>
            [row.tag_name, row.sub_tag_name, row.group_type, row.category, row.description]
                .join(" ")
                .toLowerCase()
                .includes(q),
        );
    }, [tagsQuery.data, search]);

    return (
        <div className="flex h-full flex-col gap-5 p-6">
            <div className="flex items-start justify-between gap-4 flex-wrap">
                <div>
                    <h1 className="text-h1 font-bold text-text">Catalog</h1>
                    <p className="mt-1 text-body-md text-text-subtle">
                        Maintain Pidilite product names and feedback tags used by insights and reports.
                    </p>
                </div>
                {tab === "products" ? (
                    <Button variant="action" className="flex items-center gap-2" onClick={() => setProductModal("new")}>
                        <LuPlus className="h-4 w-4" /> Add product
                    </Button>
                ) : (
                    <Button variant="action" className="flex items-center gap-2" onClick={() => setTagModal("new")}>
                        <LuPlus className="h-4 w-4" /> Add tag
                    </Button>
                )}
            </div>

            <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-surface overflow-hidden">
                <div className="flex items-center justify-between gap-4 border-b border-border px-5 py-3 flex-wrap">
                    <div className="flex gap-1 rounded-md bg-bg p-1">
                        <button
                            type="button"
                            className={`flex items-center gap-2 rounded px-3 py-1.5 text-body-sm ${tab === "products" ? "bg-surface text-brand font-medium" : "text-text-subtle"}`}
                            onClick={() => { setTab("products"); setSearch(""); }}
                        >
                            <LuPackage className="h-4 w-4" /> Products
                        </button>
                        <button
                            type="button"
                            className={`flex items-center gap-2 rounded px-3 py-1.5 text-body-sm ${tab === "tags" ? "bg-surface text-brand font-medium" : "text-text-subtle"}`}
                            onClick={() => { setTab("tags"); setSearch(""); }}
                        >
                            <LuTags className="h-4 w-4" /> Tags
                        </button>
                    </div>
                    <SearchInput
                        value={search}
                        placeholder={tab === "products" ? "Search products…" : "Search tags, group, category…"}
                        onChange={setSearch}
                    />
                </div>

                <div className="app-scrollbar min-h-0 flex-1 overflow-auto">
                    {tab === "products" ? (
                        <table className="w-full min-w-[720px]">
                            <thead className="sticky top-0 z-10">
                                <tr className="border-b border-border bg-bg">
                                    {["PRODUCT NAME", "SHORT CODE", "DESCRIPTION", "STATUS", "ACTIONS"].map((label) => (
                                        <th key={label} className="px-5 py-3 text-left text-label-sm text-text-disabled tracking-widest">{label}</th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {productsQuery.isLoading ? (
                                    <TableLoading colSpan={5} />
                                ) : products.length === 0 ? (
                                    <TableEmpty colSpan={5} message="No products found." />
                                ) : products.map((row, idx) => (
                                    <tr key={row.id} className={`border-b border-border ${idx % 2 !== 0 ? "bg-bg/40" : ""}`}>
                                        <td className="px-5 py-3.5 text-body-sm font-medium text-text">{row.product_name}</td>
                                        <td className="px-5 py-3.5 text-body-sm text-text-subtle">{row.short_code || "—"}</td>
                                        <td className="px-5 py-3.5 text-body-sm text-text-subtle">{row.description || "—"}</td>
                                        <td className="px-5 py-3.5 text-body-sm">{row.is_active === false ? "Inactive" : "Active"}</td>
                                        <td className="px-5 py-3.5">
                                            <div className="flex gap-2">
                                                <Button variant="action" onClick={() => setProductModal(row)}><LuPencil className="h-3.5 w-3.5" /></Button>
                                                <Button variant="secondary" onClick={() => setDeleteProductId(row.id)}><LuTrash2 className="h-3.5 w-3.5" /></Button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    ) : (
                        <table className="w-full min-w-[960px]">
                            <thead className="sticky top-0 z-10">
                                <tr className="border-b border-border bg-bg">
                                    {["ID", "TAG", "SUB-TAG", "GROUP", "CATEGORY", "DESCRIPTION", "STATUS", "ACTIONS"].map((label) => (
                                        <th key={label} className="px-5 py-3 text-left text-label-sm text-text-disabled tracking-widest">{label}</th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {tagsQuery.isLoading ? (
                                    <TableLoading colSpan={8} />
                                ) : tags.length === 0 ? (
                                    <TableEmpty colSpan={8} message="No tags found." />
                                ) : tags.map((row, idx) => (
                                    <tr key={String(tagKey(row))} className={`border-b border-border ${idx % 2 !== 0 ? "bg-bg/40" : ""}`}>
                                        <td className="px-5 py-3.5 text-body-sm text-text-subtle">{row.tag_id ?? row.id ?? "—"}</td>
                                        <td className="px-5 py-3.5 text-body-sm font-medium text-text">{row.tag_name}</td>
                                        <td className="px-5 py-3.5 text-body-sm text-text-subtle">{row.sub_tag_name || "—"}</td>
                                        <td className="px-5 py-3.5 text-body-sm text-text-subtle">{row.group_type || "—"}</td>
                                        <td className="px-5 py-3.5 text-body-sm text-text-subtle">{row.category || "—"}</td>
                                        <td className="px-5 py-3.5 text-body-sm text-text-subtle">{row.description || "—"}</td>
                                        <td className="px-5 py-3.5 text-body-sm">{row.is_active === false ? "Inactive" : "Active"}</td>
                                        <td className="px-5 py-3.5">
                                            <div className="flex gap-2">
                                                <Button variant="action" onClick={() => setTagModal(row)}><LuPencil className="h-3.5 w-3.5" /></Button>
                                                <Button variant="secondary" onClick={() => setDeleteTagId(tagKey(row))}><LuTrash2 className="h-3.5 w-3.5" /></Button>
                                            </div>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    )}
                </div>
            </div>

            {productModal === "new" && <ProductModal product={null} onClose={() => setProductModal(null)} />}
            {productModal && productModal !== "new" && <ProductModal product={productModal} onClose={() => setProductModal(null)} />}
            {tagModal === "new" && <TagModal tag={null} onClose={() => setTagModal(null)} />}
            {tagModal && tagModal !== "new" && <TagModal tag={tagModal} onClose={() => setTagModal(null)} />}

            <ConfirmationDialog
                open={!!deleteProductId}
                title="Delete product"
                message="Delete this product from the catalog? Feedback that still references it may block delete — deactivate instead if needed."
                confirmLabel="Delete"
                variant="danger"
                isLoading={deleteProductMutation.isPending}
                onConfirm={async () => {
                    if (!deleteProductId) return;
                    try {
                        await deleteProductMutation.mutateAsync(deleteProductId);
                        toast.success("Product deleted");
                    } catch (err: any) {
                        toast.error(err.message || "Delete failed");
                    }
                    setDeleteProductId(null);
                }}
                onCancel={() => setDeleteProductId(null)}
            />
            <ConfirmationDialog
                open={deleteTagId != null}
                title="Delete tag"
                message="Delete this tag? Links from existing feedback will also be removed."
                confirmLabel="Delete"
                variant="danger"
                isLoading={deleteTagMutation.isPending}
                onConfirm={async () => {
                    if (deleteTagId == null) return;
                    try {
                        await deleteTagMutation.mutateAsync(deleteTagId);
                        toast.success("Tag deleted");
                    } catch (err: any) {
                        toast.error(err.message || "Delete failed");
                    }
                    setDeleteTagId(null);
                }}
                onCancel={() => setDeleteTagId(null)}
            />
        </div>
    );
}
