import taxonomyJson from "./feedback_taxonomy.json";
import {
    NO_PRODUCT_LABEL,
    type BreakdownRow,
    type DrillScope,
    type FeedbackFactRow,
    type FeedbackGroup,
    type MatrixColumn,
    type MatrixRow,
    type ReportFilters,
    type ReportProductCount,
    type ReportSummaryCategory,
    type ReportSummaryTag,
    type TaxonomyTag,
} from "./types";

const taxonomy: TaxonomyTag[] = (taxonomyJson as { taxonomy: TaxonomyTag[] }).taxonomy;

export function getTaxonomy(group: FeedbackGroup): TaxonomyTag[] {
    return taxonomy.filter((t) => t.feedback_group === group);
}

function norm(value?: string | null): string {
    return (value || "")
        .replaceAll("\u00a0", " ")
        .replace(/[\u2013\u2014]/g, "-")
        .replace(/\s+/g, " ")
        .trim()
        .toLowerCase();
}

function display(value?: string | null): string {
    return (value || "").replaceAll("\u00a0", " ").replace(/\s+/g, " ").trim();
}

function displayBody(value?: string | null): string {
    return (value || "").replaceAll("\u00a0", " ").replaceAll("\r\n", "\n").trim();
}

function distinctCount(ids: Iterable<string>): number {
    return new Set(Array.from(ids).filter(Boolean)).size;
}

function factForGroup(fact: FeedbackFactRow[], group: FeedbackGroup): FeedbackFactRow[] {
    return fact.filter((row) => norm(row.feedback_group) === norm(group));
}

function matchingIds(fact: FeedbackFactRow[], tax: TaxonomyTag, product?: string): Set<string> {
    const ids = new Set<string>();
    const taxTag = norm(tax.feedback_tag);
    const taxSub = norm(tax.feedback_sub_tag);
    const taxCat = norm(tax.feedback_category);
    const productKey = product ? norm(product) : "";

    for (const row of fact) {
        if (!row.feedback_id) continue;
        if (norm(row.feedback_category) !== taxCat) continue;
        if (productKey && norm(row.product_name) !== productKey) continue;

        const rowTag = norm(row.feedback_tag);
        const rowSub = norm(row.feedback_sub_tag);
        const matches = taxSub
            ? rowTag === taxTag || rowTag === taxSub || rowSub === taxSub
            : rowTag === taxTag;
        if (matches) ids.add(row.feedback_id);
    }
    return ids;
}

function isGuidanceSubTag(sub?: string | null): boolean {
    const text = display(sub);
    if (!text) return false;
    return text.length > 40 || /^if comp/i.test(text);
}

function taxonomyForMatrix(group: FeedbackGroup): TaxonomyTag[] {
    return getTaxonomy(group)
        .filter((t) => {
            if (group === "PDT GROUP" && t.feedback_category === "Marine") return false;
            return true;
        })
        .map((t) => (isGuidanceSubTag(t.feedback_sub_tag) ? { ...t, feedback_sub_tag: null } : t));
}

function matrixTaxonomy(group: FeedbackGroup, showSubTags: boolean): TaxonomyTag[] {
    const rows = taxonomyForMatrix(group);

    if (showSubTags) {
        const hasSub = new Set(
            rows.filter((t) => t.feedback_sub_tag).map((t) => `${t.feedback_category}|${t.feedback_tag}`),
        );
        return rows.filter((t) => {
            if (t.feedback_sub_tag) return true;
            return !hasSub.has(`${t.feedback_category}|${t.feedback_tag}`);
        });
    }

    return rows.filter((t) => !t.feedback_sub_tag);
}

function totalLabelForCategory(category: string): string {
    if (category === "Dealer-related") return "Total Dealer related";
    if (category === "User Meets") return "Total User Meet";
    return `Total ${category}`;
}

export function buildTagMatrix(
    fact: FeedbackFactRow[],
    group: FeedbackGroup,
    options: { showSubTags?: boolean; categoryTotals?: boolean } = {},
): MatrixRow[] {
    const showSubTags = options.showSubTags ?? false;
    const categoryTotals = options.categoryTotals ?? group !== "PDT GROUP";
    const scoped = factForGroup(fact, group);
    const tags = matrixTaxonomy(group, showSubTags);
    const rows: MatrixRow[] = [];
    let grand = 0;
    let currentCategory = "";
    let categoryIds = new Set<string>();

    const flushCategory = () => {
        if (!categoryTotals || !currentCategory) return;
        rows.push({
            kind: "total",
            feedback_category: totalLabelForCategory(currentCategory),
            feedback_count: distinctCount(categoryIds),
            total_label: totalLabelForCategory(currentCategory),
            drill: { group, level: "category", feedback_category: currentCategory },
        });
    };

    for (const tax of tags) {
        if (tax.feedback_category !== currentCategory) {
            flushCategory();
            currentCategory = tax.feedback_category;
            categoryIds = new Set<string>();
        }
        const ids = matchingIds(scoped, tax);
        ids.forEach((id) => categoryIds.add(id));
        const count = distinctCount(ids);
        grand += count;
        const sub = showSubTags ? display(tax.feedback_sub_tag) : "";
        rows.push({
            kind: "data",
            feedback_group: group,
            feedback_category: tax.feedback_category,
            feedback_tag: tax.feedback_tag,
            feedback_sub_tag: sub || undefined,
            feedback_count: count || null,
            drill: {
                group,
                level: sub ? "sub_tag" : "tag",
                feedback_category: tax.feedback_category,
                feedback_tag: tax.feedback_tag,
                feedback_sub_tag: sub || undefined,
            },
        });
    }
    flushCategory();

    if (!categoryTotals) {
        rows.push({
            kind: "total",
            feedback_group: "Total",
            feedback_count: grand,
            total_label: "Total",
            drill: { group, level: "group" },
        });
    }

    return rows;
}

export function buildTagMatrixFromSummary(
    group: FeedbackGroup,
    tags: ReportSummaryTag[],
    categories: ReportSummaryCategory[] = [],
    options: { showSubTags?: boolean; categoryTotals?: boolean; search?: string } = {},
): MatrixRow[] {
    const showSubTags = options.showSubTags ?? false;
    const categoryTotals = options.categoryTotals ?? group !== "PDT GROUP";
    const taxRows = matrixTaxonomy(group, showSubTags);
    const rows: MatrixRow[] = [];
    let grand = 0;
    let currentCategory = "";
    let categorySum = 0;
    let categoryHasRows = false;
    const needle = norm(options.search);

    const flushCategory = () => {
        if (!categoryTotals || !currentCategory || !categoryHasRows) return;
        const fromApi = categories.find(
            (row) => norm(row.feedback_category) === norm(currentCategory),
        );
        rows.push({
            kind: "total",
            feedback_category: totalLabelForCategory(currentCategory),
            feedback_count: fromApi ? fromApi.feedback_count : categorySum,
            total_label: totalLabelForCategory(currentCategory),
            drill: { group, level: "category", feedback_category: currentCategory },
        });
    };

    for (const tax of taxRows) {
        if (tax.feedback_category !== currentCategory) {
            flushCategory();
            currentCategory = tax.feedback_category;
            categorySum = 0;
            categoryHasRows = false;
        }
        const count = summaryTagCount(tags, tax.feedback_category, tax.feedback_tag);
        if (needle) {
            const labelHit =
                norm(tax.feedback_tag).includes(needle) ||
                norm(tax.feedback_category).includes(needle);
            if (!labelHit && !count) continue;
        }
        categorySum += count;
        grand += count;
        categoryHasRows = true;
        const sub = showSubTags ? display(tax.feedback_sub_tag) : "";
        rows.push({
            kind: "data",
            feedback_group: group,
            feedback_category: tax.feedback_category,
            feedback_tag: tax.feedback_tag,
            feedback_sub_tag: sub || undefined,
            feedback_count: count || null,
            drill: {
                group,
                level: sub ? "sub_tag" : "tag",
                feedback_category: tax.feedback_category,
                feedback_tag: tax.feedback_tag,
                feedback_sub_tag: sub || undefined,
            },
        });
    }
    flushCategory();

    if (!categoryTotals) {
        rows.push({
            kind: "total",
            feedback_group: "Total",
            feedback_count: grand,
            total_label: "Total",
            drill: { group, level: "group" },
        });
    }

    return rows;
}

function summaryTagCount(tags: ReportSummaryTag[], category: string, tag: string): number {
    const cat = norm(category);
    const key = norm(tag);
    let total = 0;
    for (const row of tags) {
        if (norm(row.feedback_category) !== cat) continue;
        if (norm(row.feedback_tag) === key) total += row.feedback_count || 0;
    }
    return total;
}

export function buildProductRowsFromCounts(
    drill: DrillScope,
    items: ReportProductCount[],
): MatrixRow[] {
    return items.map((item) => {
        const product = display(item.product_name) || NO_PRODUCT_LABEL;
        return {
            kind: "data" as const,
            feedback_group: drill.group,
            product_name: product,
            feedback_category: drill.feedback_category,
            feedback_tag: drill.feedback_tag,
            feedback_count: item.feedback_count || null,
            drill: {
                group: drill.group,
                level: drill.feedback_sub_tag ? "sub_tag" : drill.feedback_tag ? "tag" : "product",
                product_name: product,
                feedback_category: drill.feedback_category,
                feedback_tag: drill.feedback_tag,
                feedback_sub_tag: drill.feedback_sub_tag,
            },
        };
    });
}

export function buildDetailRowsFromItems(items: FeedbackFactRow[], drill: DrillScope): MatrixRow[] {
    return items.map((row) => {
        const category = display(row.feedback_category);
        const tag = display(row.feedback_tag);
        const sub = display(row.feedback_sub_tag);
        const product = display(row.product_name);
        const callDatetime =
            display(row.call_datetime) ||
            display(row.call_date) ||
            display(row.feedback_created_at);
        return {
            kind: "data" as const,
            feedback_group: display(row.feedback_group) || drill.group,
            product_name: product,
            feedback_category: category,
            feedback_tag: tag,
            feedback_sub_tag: sub,
            feedback_summary_ai: displayBody(row.feedback_summary_ai),
            feedback_excerpt: displayBody(row.feedback_excerpt),
            full_conversation: row.feedback_id ? "available" : "",
            file_name: display(row.file_name),
            call_datetime: callDatetime,
            job_id: row.job_id || undefined,
            feedback_id: row.feedback_id || undefined,
            drill: {
                group: drill.group,
                level: "item",
                product_name: product || undefined,
                feedback_category: category || undefined,
                feedback_tag: tag || undefined,
                feedback_sub_tag: sub || undefined,
                feedback_id: row.feedback_id || undefined,
            },
        };
    });
}

export function filtersForDrill(base: ReportFilters, drill: DrillScope): ReportFilters {
    return {
        ...base,
        feedback_group: drill.group,
        product_name: drill.product_name || base.product_name,
        feedback_category: drill.feedback_category,
        feedback_tag: drill.feedback_tag,
        feedback_sub_tag: drill.feedback_sub_tag,
        page: undefined,
        page_size: undefined,
        sort_by: undefined,
        sort_dir: undefined,
    };
}

export function buildProductMatrix(
    fact: FeedbackFactRow[],
    options: { showSubTags?: boolean } = {},
): MatrixRow[] {
    const showSubTags = options.showSubTags ?? false;
    const scoped = factForGroup(fact, "PDT GROUP");
    const tags = matrixTaxonomy("PDT GROUP", showSubTags);
    const products = Array.from(
        new Set(scoped.map((r) => display(r.product_name)).filter(Boolean)),
    ).sort((a, b) => a.localeCompare(b));

    const productList = products.length > 0 ? products : [];
    const rows: MatrixRow[] = [];

    for (const product of productList) {
        let productIds = new Set<string>();
        for (const tax of tags) {
            const ids = matchingIds(scoped, tax, product);
            ids.forEach((id) => productIds.add(id));
            const sub = showSubTags ? display(tax.feedback_sub_tag) : "";
            rows.push({
                kind: "data",
                feedback_group: "PDT GROUP",
                product_name: product,
                feedback_category: tax.feedback_category,
                feedback_tag: tax.feedback_tag,
                feedback_sub_tag: sub || undefined,
                feedback_count: distinctCount(ids) || null,
                drill: {
                    group: "PDT GROUP",
                    level: sub ? "sub_tag" : "tag",
                    product_name: product,
                    feedback_category: tax.feedback_category,
                    feedback_tag: tax.feedback_tag,
                    feedback_sub_tag: sub || undefined,
                },
            });
        }
        rows.push({
            kind: "total",
            product_name: `Total ${product}`,
            feedback_count: distinctCount(productIds),
            total_label: `Total ${product}`,
            drill: { group: "PDT GROUP", level: "product", product_name: product },
        });
    }

    return rows;
}

export function buildDetailRows(
    fact: FeedbackFactRow[],
    group: FeedbackGroup,
): MatrixRow[] {
    const scoped = factForGroup(fact, group).slice().sort((a, b) => {
        const cat = display(a.feedback_category).localeCompare(display(b.feedback_category));
        if (cat !== 0) return cat;
        const tag = display(a.feedback_tag).localeCompare(display(b.feedback_tag));
        if (tag !== 0) return tag;
        return display(a.product_name).localeCompare(display(b.product_name));
    });

    const rows: MatrixRow[] = [];
    let currentCategory = "";
    let categoryIds = new Set<string>();

    const flush = () => {
        if (!currentCategory) return;
        const count = distinctCount(categoryIds);
        const countText = String(count);
        rows.push({
            kind: "total",
            feedback_category: totalLabelForCategory(currentCategory),
            feedback_tag: group === "PDT GROUP" ? countText : undefined,
            feedback_sub_tag: group !== "PDT GROUP" ? countText : undefined,
            feedback_count: count,
            total_label: totalLabelForCategory(currentCategory),
            drill: { group, level: "category", feedback_category: currentCategory },
        });
    };

    for (const row of scoped) {
        const category = display(row.feedback_category) || "UNKNOWN";
        if (category !== currentCategory) {
            flush();
            currentCategory = category;
            categoryIds = new Set<string>();
        }
        if (row.feedback_id) categoryIds.add(row.feedback_id);
        const tag = display(row.feedback_tag);
        const sub = display(row.feedback_sub_tag);
        const product = display(row.product_name);
        rows.push({
            kind: "data",
            feedback_group: group,
            feedback_category: category,
            feedback_tag: tag,
            feedback_sub_tag: sub,
            product_name: product,
            feedback_summary_ai: displayBody(row.feedback_summary_ai),
            feedback_excerpt: displayBody(row.feedback_excerpt),
            full_conversation: displayBody(row.full_conversation),
            full_conversation_raw: displayBody(row.full_conversation_raw),
            competitors_mentioned: display(row.competitors_mentioned),
            feedback_id: row.feedback_id || undefined,
            drill: {
                group,
                level: "item",
                product_name: product || undefined,
                feedback_category: category,
                feedback_tag: tag || undefined,
                feedback_sub_tag: sub || undefined,
                feedback_id: row.feedback_id || undefined,
            },
        });
    }
    flush();
    return rows;
}

export function columnsForOverview(): MatrixColumn[] {
    return ["feedback_category", "feedback_tag", "feedback_count"];
}

export function columnsForProductDrill(drill: DrillScope): MatrixColumn[] {
    const cols: MatrixColumn[] = ["product_name"];
    if (drill.level === "group" || drill.level === "category" || !drill.feedback_tag) {
        cols.push("feedback_category", "feedback_tag");
    }
    cols.push("feedback_count");
    return cols;
}

export function columnsForDetail(
    drill: DrillScope,
    includeProduct: boolean,
): MatrixColumn[] {
    const cols: MatrixColumn[] = [];
    if (includeProduct && !drill.product_name) cols.push("product_name");
    if (!drill.feedback_category) cols.push("feedback_category");
    if (!drill.feedback_tag) cols.push("feedback_tag");
    cols.push("call_datetime", "audio", "file_name", "feedback_summary_ai", "feedback_excerpt", "full_conversation");
    return cols;
}

function tagKey(category?: string | null, tag?: string | null, sub?: string | null): string {
    return `${norm(category)}|${norm(tag)}|${norm(sub)}`;
}

function uniqueProducts(rows: FeedbackFactRow[]): string[] {
    const seen = new Map<string, string>();
    let hasNone = false;
    for (const row of rows) {
        const label = display(row.product_name);
        if (!label) {
            hasNone = true;
            continue;
        }
        const key = norm(label);
        if (!seen.has(key)) seen.set(key, label);
    }
    const names = Array.from(seen.values()).sort((a, b) => a.localeCompare(b));
    if (hasNone) names.push(NO_PRODUCT_LABEL);
    return names;
}

function uniqueTagCombos(rows: FeedbackFactRow[]): { category: string; tag: string; sub?: string }[] {
    const seen = new Map<string, { category: string; tag: string; sub?: string }>();
    for (const row of rows) {
        const category = display(row.feedback_category);
        const tag = display(row.feedback_tag);
        const sub = display(row.feedback_sub_tag) || undefined;
        const key = tagKey(category, tag, sub);
        if (!seen.has(key)) seen.set(key, { category, tag, sub });
    }
    return Array.from(seen.values());
}

function taxonomyCombosForDrill(drill: DrillScope): { category: string; tag: string; sub?: string }[] {
    return matrixTaxonomy(drill.group, false)
        .filter((tax) => {
            if (drill.feedback_category && norm(tax.feedback_category) !== norm(drill.feedback_category)) {
                return false;
            }
            if (drill.feedback_tag && norm(tax.feedback_tag) !== norm(drill.feedback_tag)) return false;
            return true;
        })
        .map((tax) => ({
            category: tax.feedback_category,
            tag: tax.feedback_tag,
            sub: undefined,
        }));
}

export function buildDrillProductRows(fact: FeedbackFactRow[], drill: DrillScope): MatrixRow[] {
    const scoped = factMatchingDrill(fact, drill);
    const products = uniqueProducts(scoped);
    if (products.length === 0) return [];

    // Tag drill table only shows product + count. One row per product so hidden
    // sub-tags cannot split Fevicol MARINE into 2 / 2 / 1.
    if (drill.feedback_tag) {
        return products.map((product) => {
            const ids = scoped
                .filter((row) =>
                    product === NO_PRODUCT_LABEL
                        ? !display(row.product_name)
                        : norm(row.product_name) === norm(product),
                )
                .map((row) => row.feedback_id || "");
            const count = distinctCount(ids);
            return {
                kind: "data" as const,
                feedback_group: drill.group,
                product_name: product,
                feedback_category: drill.feedback_category,
                feedback_tag: drill.feedback_tag,
                feedback_count: count || null,
                drill: {
                    group: drill.group,
                    level: drill.feedback_sub_tag ? "sub_tag" : "tag",
                    product_name: product,
                    feedback_category: drill.feedback_category,
                    feedback_tag: drill.feedback_tag,
                    feedback_sub_tag: drill.feedback_sub_tag,
                },
            };
        });
    }

    const pad = drill.level === "group" || drill.level === "category";
    const combos = pad ? taxonomyCombosForDrill(drill) : uniqueTagCombos(scoped);
    const rows: MatrixRow[] = [];

    for (const product of products) {
        const productRows = scoped.filter((row) =>
            product === NO_PRODUCT_LABEL
                ? !display(row.product_name)
                : norm(row.product_name) === norm(product),
        );
        const productIds = new Set<string>();
        for (const combo of combos) {
            const matched = productRows.filter((row) => {
                if (norm(row.feedback_category) !== norm(combo.category)) return false;
                if (norm(row.feedback_tag) !== norm(combo.tag) && norm(row.feedback_sub_tag) !== norm(combo.tag)) {
                    return false;
                }
                if (combo.sub) {
                    return norm(row.feedback_sub_tag) === norm(combo.sub) || norm(row.feedback_tag) === norm(combo.sub);
                }
                return true;
            });
            matched.forEach((row) => {
                if (row.feedback_id) productIds.add(row.feedback_id);
            });
            const count = distinctCount(matched.map((row) => row.feedback_id || ""));
            if (!pad && !count) continue;
            rows.push({
                kind: "data",
                feedback_group: drill.group,
                product_name: product,
                feedback_category: combo.category,
                feedback_tag: combo.tag,
                feedback_sub_tag: combo.sub,
                feedback_count: count || null,
                drill: {
                    group: drill.group,
                    level: combo.sub ? "sub_tag" : "tag",
                    product_name: product,
                    feedback_category: combo.category,
                    feedback_tag: combo.tag,
                    feedback_sub_tag: combo.sub,
                },
            });
        }
        if (pad) {
            rows.push({
                kind: "total",
                product_name: `Total ${product}`,
                feedback_count: distinctCount(productIds),
                total_label: `Total ${product}`,
                drill: {
                    ...drill,
                    level: "product",
                    product_name: product,
                },
            });
        }
    }
    return rows;
}

export function buildDrillSubTagRows(fact: FeedbackFactRow[], drill: DrillScope): MatrixRow[] {
    if (drill.level === "sub_tag" || drill.level === "item") return [];
    const scoped = factMatchingDrill(fact, drill);
    const hasSub = scoped.some((row) => display(row.feedback_sub_tag));
    if (!hasSub) return [];

    const buckets = new Map<string, { label: string; ids: Set<string> }>();
    for (const row of scoped) {
        const label = display(row.feedback_sub_tag);
        if (!label) continue;
        const key = norm(label);
        let bucket = buckets.get(key);
        if (!bucket) {
            bucket = { label, ids: new Set<string>() };
            buckets.set(key, bucket);
        }
        if (row.feedback_id) bucket.ids.add(row.feedback_id);
    }

    return Array.from(buckets.values())
        .sort((a, b) => a.label.localeCompare(b.label))
        .map((bucket) => ({
            kind: "data" as const,
            feedback_group: drill.group,
            feedback_category: drill.feedback_category,
            feedback_tag: drill.feedback_tag,
            feedback_sub_tag: bucket.label,
            feedback_count: bucket.ids.size,
            drill: {
                ...drill,
                level: "sub_tag" as const,
                feedback_sub_tag: bucket.label,
            },
        }));
}

export function buildDrillDetailRows(fact: FeedbackFactRow[], drill: DrillScope): MatrixRow[] {
    return uniqueFeedbackItems(factMatchingDrill(fact, drill)).map((row) => {
        const category = display(row.feedback_category);
        const tag = display(row.feedback_tag);
        const sub = display(row.feedback_sub_tag);
        const product = display(row.product_name);
        return {
            kind: "data" as const,
            feedback_group: display(row.feedback_group) || drill.group,
            product_name: product,
            feedback_category: category,
            feedback_tag: tag,
            feedback_sub_tag: sub,
            feedback_summary_ai: displayBody(row.feedback_summary_ai),
            feedback_excerpt: displayBody(row.feedback_excerpt),
            full_conversation: displayBody(row.full_conversation),
            full_conversation_raw: displayBody(row.full_conversation_raw),
            competitors_mentioned: display(row.competitors_mentioned),
            file_name: display(row.file_name),
            call_datetime: display(row.call_date) || display(row.feedback_created_at),
            job_id: row.job_id || undefined,
            feedback_id: row.feedback_id || undefined,
            drill: {
                group: drill.group,
                level: "item",
                product_name: product || undefined,
                feedback_category: category || undefined,
                feedback_tag: tag || undefined,
                feedback_sub_tag: sub || undefined,
                feedback_id: row.feedback_id || undefined,
            },
        };
    });
}

export function factMatchingDrill(fact: FeedbackFactRow[], drill: DrillScope): FeedbackFactRow[] {
    return fact.filter((row) => {
        if (norm(row.feedback_group) !== norm(drill.group)) return false;
        if (drill.feedback_id) return row.feedback_id === drill.feedback_id;
        if (drill.product_name) {
            const wantNone = norm(drill.product_name) === norm(NO_PRODUCT_LABEL);
            const rowNone = !display(row.product_name);
            if (wantNone ? !rowNone : norm(row.product_name) !== norm(drill.product_name)) {
                return false;
            }
        }
        if (drill.feedback_category && norm(row.feedback_category) !== norm(drill.feedback_category)) {
            return false;
        }
        if (drill.feedback_sub_tag) {
            const sub = norm(drill.feedback_sub_tag);
            return norm(row.feedback_sub_tag) === sub || norm(row.feedback_tag) === sub;
        }
        if (drill.feedback_tag) {
            const tag = norm(drill.feedback_tag);
            return norm(row.feedback_tag) === tag || norm(row.feedback_sub_tag) === tag;
        }
        return true;
    });
}

export function uniqueFeedbackItems(fact: FeedbackFactRow[]): FeedbackFactRow[] {
    const seen = new Set<string>();
    const items: FeedbackFactRow[] = [];
    for (const row of fact) {
        const key = row.feedback_id || `${row.job_id}-${row.feedback_tag}-${items.length}`;
        if (seen.has(key)) continue;
        seen.add(key);
        items.push(row);
    }
    return items;
}

export function buildBreakdown(fact: FeedbackFactRow[], drill: DrillScope): BreakdownRow[] {
    const scoped = factMatchingDrill(fact, drill);
    if (drill.level === "sub_tag" || drill.level === "item") {
        return [];
    }

    const hasSubTags = scoped.some((row) => display(row.feedback_sub_tag));
    if (drill.level === "tag" && !hasSubTags) {
        return [];
    }

    const buckets = new Map<string, { label: string; ids: Set<string>; next: DrillScope }>();
    const useProduct = drill.level === "group" && drill.group === "PDT GROUP"
        && scoped.some((row) => display(row.product_name));
    const field: "product_name" | "feedback_category" | "feedback_tag" | "feedback_sub_tag" =
        drill.level === "tag"
            ? "feedback_sub_tag"
            : drill.level === "group" && useProduct
                ? "product_name"
                : drill.level === "group" || drill.level === "product"
                    ? "feedback_category"
                    : "feedback_tag";

    for (const row of scoped) {
        const label = display(row[field]) || "(untagged)";
        const key = norm(label);
        let bucket = buckets.get(key);
        if (!bucket) {
            const next: DrillScope = { ...drill };
            if (field === "product_name") {
                next.level = "product";
                next.product_name = label;
            } else if (field === "feedback_category") {
                next.level = "category";
                next.feedback_category = label;
            } else if (field === "feedback_tag") {
                next.level = "tag";
                next.feedback_tag = label;
            } else {
                next.level = "sub_tag";
                next.feedback_sub_tag = label;
            }
            bucket = { label, ids: new Set<string>(), next };
            buckets.set(key, bucket);
        }
        if (row.feedback_id) bucket.ids.add(row.feedback_id);
    }

    return Array.from(buckets.values())
        .map((bucket) => ({
            label: bucket.label,
            count: bucket.ids.size,
            drill: bucket.next,
        }))
        .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

export function drillTitle(drill: DrillScope): string {
    if (drill.level === "item") return "Feedback detail";
    if (drill.feedback_tag) return drill.feedback_tag;
    if (drill.feedback_category) return drill.feedback_category;
    if (drill.product_name) return drill.product_name;
    return drill.group;
}

export function drillPath(drill: DrillScope): string[] {
    const parts: string[] = [drill.group];
    if (drill.product_name) parts.push(drill.product_name);
    if (drill.feedback_category) parts.push(drill.feedback_category);
    if (drill.feedback_tag) parts.push(drill.feedback_tag);
    return parts;
}
