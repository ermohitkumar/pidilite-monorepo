import { groupSummaryLines, summaryDisplayText } from "@/components/reports/FormattedSummary";

import taxonomyJson from "./feedback_taxonomy.json";
import {
    NO_PRODUCT_LABEL,
    type BreakdownRow,
    type DrillScope,
    type FeedbackFactRow,
    type FeedbackGroup,
    type MatrixColumn,
    type MatrixRow,
    type PeriodSummaryRecord,
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

function byFeedbackCountDesc(a: MatrixRow, b: MatrixRow): number {
    const diff = (b.feedback_count || 0) - (a.feedback_count || 0);
    if (diff) return diff;
    return display(a.feedback_tag).localeCompare(display(b.feedback_tag));
}

/** The fact view stores the level-2 tag in feedback_category. Drop a level-1 parent such as "Product". */
export function categoryForTagDrill(category?: string | null, tag?: string | null): string | undefined {
    const tagKey = norm(tag);
    const categoryKey = norm(category);
    if (!tagKey || !categoryKey || tagKey === categoryKey) return category || undefined;
    const parentOfTag = taxonomy.some(
        (item) => norm(item.feedback_category) === tagKey && norm(item.level_1) === categoryKey,
    );
    if (parentOfTag) return tag || undefined;
    return category || undefined;
}

function displayBody(value?: string | null): string {
    return (value || "").replaceAll("\u00a0", " ").replaceAll("\r\n", "\n").trim();
}

function labelKeys(value?: string | null): string[] {
    const needle = norm(value);
    if (!needle) return [];
    const keys = [needle];
    const suffix = needle.split(" - ").pop()?.trim();
    if (suffix && !keys.includes(suffix)) keys.push(suffix);
    return keys;
}

function labelsOverlap(left?: string | null, right?: string | null): boolean {
    const a = new Set(labelKeys(left));
    if (!a.size) return false;
    return labelKeys(right).some((key) => a.has(key));
}

export function tagLabelsMatch(left?: string | null, right?: string | null): boolean {
    return labelsOverlap(left, right);
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
    const categoryTotals = options.categoryTotals ?? true;
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
    options: { showSubTags?: boolean; categoryTotals?: boolean; search?: string; periodTags?: PeriodSummaryRecord[] } = {},
): MatrixRow[] {
    const showSubTags = options.showSubTags ?? false;
    const categoryTotals = options.categoryTotals ?? true;
    const taxRows = matrixTaxonomy(group, showSubTags);
    const rows: MatrixRow[] = [];
    void categories;
    let grand = 0;
    let currentCategory = "";
    let currentLevel1 = "";
    let categoryHasRows = false;
    const needle = norm(options.search);

    let tagCount = 0;
    let tagNarrative: string | undefined;
    let tagSentiment: string | undefined;

    const pushTag = () => {
        if (!currentCategory || !categoryHasRows || !tagCount) return;
        rows.push({
            kind: "data",
            feedback_group: group,
            feedback_category: currentLevel1 || currentCategory,
            feedback_tag: currentCategory,
            feedback_count: tagCount,
            feedback_summary_ai: tagNarrative,
            sentiment: tagSentiment,
            drill: {
                group,
                level: "tag",
                feedback_category: currentCategory,
                feedback_tag: currentCategory,
            },
        });
    };

    for (const tax of taxRows) {
        if (tax.feedback_category !== currentCategory) {
            pushTag();
            currentCategory = tax.feedback_category;
            currentLevel1 = display(tax.level_1);
            categoryHasRows = false;
            tagCount = 0;
            tagNarrative = summaryTagNarrative(tags, tax.feedback_category, tax.feedback_category, options.periodTags);
            tagSentiment = summaryTagSentiment(tags, tax.feedback_category, tax.feedback_category, options.periodTags);
        }
        const count = summaryTagCount(tags, tax.feedback_category, tax.feedback_tag);
        if (!count) continue;
        if (needle) {
            const labelHit =
                norm(tax.feedback_tag).includes(needle) ||
                norm(tax.feedback_category).includes(needle) ||
                norm(tax.level_1).includes(needle);
            if (!labelHit) continue;
        }
        tagCount += count;
        grand += count;
        categoryHasRows = true;
    }
    pushTag();

    const listed = new Set(
        taxRows.map((tax) => `${norm(tax.feedback_category)}|${norm(tax.feedback_tag)}`),
    );
    const historical: MatrixRow[] = [];
    for (const row of tags) {
        const category = display(row.feedback_category);
        const tag = display(row.feedback_tag);
        if (!tag || !(row.feedback_count || 0)) continue;
        const key = `${norm(category)}|${norm(tag)}`;
        if (listed.has(key)) continue;
        listed.add(key);
        if (needle && !norm(category).includes(needle) && !norm(tag).includes(needle)) continue;
        historical.push({
            kind: "data",
            feedback_group: group,
            feedback_category: category,
            feedback_tag: tag,
            feedback_count: row.feedback_count,
            feedback_summary_ai: displayBody(row.ai_summary),
            sentiment: display(row.sentiment) || undefined,
            drill: {
                group,
                level: "tag",
                feedback_category: category,
                feedback_tag: tag,
            },
        });
        grand += row.feedback_count || 0;
    }
    rows.unshift(...historical);
    rows.sort(byFeedbackCountDesc);

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

const SUMMARY_GROUPS: FeedbackGroup[] = ["PDT GROUP", "USER GROUP", "DEALER GROUP"];

/** Group stays on the drill so detail queries stay scoped. It is not shown in the table. */
export function groupForCategory(category?: string | null, tag?: string | null): FeedbackGroup {
    const categoryKey = norm(categoryForTagDrill(category, tag) || category || tag);
    if (!categoryKey) return "PDT GROUP";
    const match = taxonomy.find(
        (item) =>
            SUMMARY_GROUPS.includes(item.feedback_group as FeedbackGroup) &&
            (norm(item.feedback_category) === categoryKey || norm(item.level_1) === categoryKey),
    );
    return (match?.feedback_group as FeedbackGroup) || "PDT GROUP";
}

export function levelOneCategories(): string[] {
    const seen = new Set<string>();
    const ordered: string[] = [];
    for (const item of taxonomy) {
        const label = display(item.level_1);
        const key = norm(label);
        if (!label || seen.has(key)) continue;
        seen.add(key);
        ordered.push(label);
    }
    return ordered;
}

/** One row per feedback tag, labeled with its level-1 category. Group is not shown. */
export function buildCategoryTagRows(
    tags: ReportSummaryTag[],
    options: { category?: string; periodTags?: PeriodSummaryRecord[] } = {},
): MatrixRow[] {
    const wanted = norm(options.category);
    const buckets = new Map<string, {
        level1: string;
        category: string;
        group: FeedbackGroup;
        count: number;
        narrative?: string;
        sentiment?: string;
    }>();
    const counted = new Set<string>();

    for (const tax of taxonomy) {
        if (!SUMMARY_GROUPS.includes(tax.feedback_group as FeedbackGroup)) continue;
        if (tax.feedback_group === "PDT GROUP" && tax.feedback_category === "Marine") continue;
        const level1 = display(tax.level_1);
        const category = display(tax.feedback_category);
        const tag = display(tax.feedback_tag);
        if (!category || !tag) continue;
        const bucketKey = `${norm(level1)}|${norm(category)}`;
        const piece = `${bucketKey}|${norm(tag)}`;
        if (counted.has(piece)) continue;
        counted.add(piece);
        let bucket = buckets.get(bucketKey);
        if (!bucket) {
            bucket = {
                level1,
                category,
                group: tax.feedback_group as FeedbackGroup,
                count: 0,
                sentiment: summaryTagSentiment(tags, category, category, options.periodTags || []),
            };
            buckets.set(bucketKey, bucket);
        }
        bucket.count += summaryTagCount(tags, category, tag);
    }

    const rows: MatrixRow[] = [];
    for (const bucket of buckets.values()) {
        if (!bucket.count) continue;
        if (wanted && norm(bucket.level1) !== wanted) continue;
        const narrative = summaryFitsCount(
            summaryTagNarrative(tags, bucket.category, bucket.category, options.periodTags || []),
            bucket.count,
        );
        if (!narrative) continue;
        rows.push({
            kind: "data",
            feedback_category: bucket.level1 || bucket.category,
            feedback_tag: bucket.category,
            feedback_count: bucket.count,
            feedback_summary_ai: narrative,
            sentiment: bucket.sentiment,
            drill: {
                group: bucket.group,
                level: "tag",
                feedback_category: bucket.level1 || bucket.category,
                feedback_tag: bucket.category,
            },
        });
    }

    const known = new Set(
        taxonomy.map((item) => `${norm(item.feedback_category)}|${norm(item.feedback_tag)}`),
    );
    for (const row of tags) {
        const category = display(row.feedback_category);
        const tag = display(row.feedback_tag);
        if (!category || !tag || !(row.feedback_count || 0) || !hasGeneratedSummary(row)) continue;
        if (known.has(`${norm(category)}|${norm(tag)}`)) continue;
        const parent = taxonomy.find((item) => norm(item.feedback_category) === norm(category));
        const level1 = display(parent?.level_1) || category;
        if (wanted && norm(level1) !== wanted && norm(category) !== wanted) continue;
        const bucketKey = `${norm(level1)}|${norm(category)}`;
        if (buckets.has(bucketKey)) {
            const existing = rows.find(
                (item) => norm(item.feedback_category) === norm(level1) && norm(item.feedback_tag) === norm(category),
            );
            if (existing) existing.feedback_count = (existing.feedback_count || 0) + (row.feedback_count || 0);
            continue;
        }
        rows.push({
            kind: "data",
            feedback_category: level1,
            feedback_tag: category,
            feedback_count: row.feedback_count,
            feedback_summary_ai: summaryFitsCount(
                displayBody(row.ai_summary) || periodNarrative(options.periodTags || [], category, category),
                row.feedback_count || 0,
            ),
            sentiment: display(row.sentiment) || undefined,
            drill: {
                group: (parent?.feedback_group as FeedbackGroup) || "PDT GROUP",
                level: "tag",
                feedback_category: level1,
                feedback_tag: category,
            },
        });
        buckets.set(bucketKey, {
            level1,
            category,
            group: "PDT GROUP",
            count: row.feedback_count,
        });
    }

    rows.sort(byFeedbackCountDesc);
    return rows;
}

/** Level-3 tags under one level-2 category, with the same counts the summary row adds up. */
export function buildLevelThreeRows(tags: ReportSummaryTag[], levelTwo: string): MatrixRow[] {
    const parent = norm(levelTwo);
    if (!parent) return [];
    const rows: MatrixRow[] = [];
    const known = new Set<string>();

    const push = (tag: string) => {
        const key = norm(tag);
        if (!tag || !key || known.has(key)) return;
        const count = summaryTagCount(tags, levelTwo, tag);
        if (!count) return;
        known.add(key);
        const match = tags.find(
            (row) => norm(row.feedback_category) === parent && norm(row.feedback_tag) === key && hasGeneratedSummary(row),
        );
        const narrative = alignSummaryCount(groupSummaryLines(displayBody(match?.ai_summary)), count);
        if (!narrative) return;
        rows.push({
            kind: "data",
            feedback_category: levelTwo,
            feedback_tag: tag,
            feedback_count: count,
            feedback_summary_ai: narrative,
            sentiment: display(match?.sentiment) || undefined,
            drill: {
                group: groupForCategory(levelTwo, tag),
                level: "tag",
                feedback_category: levelTwo,
                feedback_tag: tag,
            },
        });
    };

    for (const tax of taxonomy) {
        if (!SUMMARY_GROUPS.includes(tax.feedback_group as FeedbackGroup)) continue;
        if (tax.feedback_group === "PDT GROUP" && tax.feedback_category === "Marine") continue;
        if (norm(tax.feedback_category) !== parent) continue;
        push(display(tax.feedback_tag));
    }
    for (const row of tags) {
        if (norm(row.feedback_category) !== parent) continue;
        push(display(row.feedback_tag));
    }

    rows.sort(byFeedbackCountDesc);
    return rows;
}

export function filtersForSummaryDrill(drill: {
    category?: string;
    tag?: string;
    theme?: string;
    product?: string;
}): ReportFilters {
    const category = categoryForTagDrill(drill.category, drill.tag);
    const theme = display(drill.theme);
    if (theme) {
        return {
            product_name: drill.product || undefined,
            feedback_category: category,
            feedback_tag: theme,
        };
    }
    const tag = drill.tag;
    const tagNamesTheCategory = Boolean(tag) && norm(tag) === norm(category);
    return {
        product_name: drill.product || undefined,
        feedback_category: category,
        feedback_tag: tagNamesTheCategory ? undefined : tag,
    };
}

function hasGeneratedSummary(row?: ReportSummaryTag): boolean {
    if (!row || row.summary_status === "error") return false;
    const text = displayBody(row.ai_summary);
    return Boolean(text) && !text.toLowerCase().startsWith("no insights");
}

function summaryTagCount(tags: ReportSummaryTag[], category: string, tag: string): number {
    const cat = norm(category);
    const key = norm(tag);
    let total = 0;
    for (const row of tags) {
        if (!hasGeneratedSummary(row)) continue;
        if (norm(row.feedback_category) !== cat) continue;
        if (norm(row.feedback_tag) === key) total += row.feedback_count || 0;
    }
    return total;
}

function themesInCategory(tags: ReportSummaryTag[], category: string): ReportSummaryTag[] {
    const cat = norm(category);
    return tags.filter((row) => norm(row.feedback_category) === cat && (row.feedback_count || 0) > 0);
}

function majoritySentiment(labels: Array<string | null | undefined>): string | undefined {
    const counts = new Map<string, number>();
    for (const label of labels) {
        const clean = (label || "").trim();
        if (!clean) continue;
        counts.set(clean, (counts.get(clean) || 0) + 1);
    }
    const rank: Record<string, number> = { Negative: 0, Neutral: 1, Positive: 2 };
    let best = "";
    let bestCount = 0;
    for (const [label, count] of counts) {
        const betterCount = count > bestCount;
        const sameCountEarlier = count === bestCount && (rank[label] ?? 9) < (rank[best] ?? 9);
        if (betterCount || sameCountEarlier) {
            best = label;
            bestCount = count;
        }
    }
    return best || undefined;
}

function tagIdsFor(category: string, tag: string, includeChildren = false): string[] {
    const cat = norm(category);
    const key = norm(tag);
    if (includeChildren && key) {
        const children = taxonomy.filter((item) => norm(item.feedback_category) === key);
        if (children.length) return children.map((item) => String(item.tag_id));
    }
    return taxonomy
        .filter((item) => {
            if (norm(item.feedback_tag) !== key) return false;
            if (!cat || cat === key) return true;
            return norm(item.feedback_category) === cat || norm(item.level_1) === cat;
        })
        .map((item) => String(item.tag_id));
}

function keyHasTagId(grainKey: string | null | undefined, tagId: string): boolean {
    return (grainKey || "").split("::").includes(tagId);
}

function labelMentionsTag(label: string | null | undefined, tag: string): boolean {
    const needle = norm(tag);
    const value = norm(label);
    if (!needle || !value || needle === "others") return value === needle;
    if (value === needle) return true;
    return value.split(/\s+[×x]\s+/).some((part) => part.trim() === needle);
}

function periodRowsForTag(
    periodTags: PeriodSummaryRecord[],
    category: string,
    tag: string,
    product?: string,
    includeChildren = false,
): PeriodSummaryRecord[] {
    const ids = tagIdsFor(category, tag, includeChildren);
    const productKey = norm(product);
    return periodTags.filter((row) => {
        const byId = ids.some((id) => keyHasTagId(row.grain_key, id));
        const byName = !byId && labelMentionsTag(row.grain_label || row.grain_key, tag);
        if (!byId && !byName) return false;
        if (!productKey || productKey === norm(NO_PRODUCT_LABEL)) return true;
        const haystack = `${norm(row.grain_label)} ${norm(row.grain_key)}`;
        return haystack.includes(productKey);
    });
}

function periodNarrative(
    periodTags: PeriodSummaryRecord[],
    category: string,
    tag: string,
    product?: string,
    includeChildren = false,
): string | undefined {
    const rows = periodRowsForTag(periodTags, category, tag, product, includeChildren);
    if (rows.some((row) => row.status === "error")) return "Updating…";
    const texts = rows
        .map((row) => summaryDisplayText(row.summary_text, row.highlights))
        .filter(Boolean);
    return texts.length ? groupSummaryLines(texts.join("\n")) : undefined;
}

/** The number in the summary is the same feedback count shown in the row. */
function alignSummaryCount(text: string | undefined, count: number): string | undefined {
    const body = (text || "").trim();
    if (!body || count < 1) return body || undefined;
    const lines = body.split("\n").map((line) => line.trim()).filter(Boolean);
    const counted = lines.filter((line) => /^\(\d+\)/.test(line));
    if (counted.length !== 1) return body;
    return lines.map((line) => line.replace(/^\(\d+\)/, `(${count})`)).join("\n");
}

function summaryFitsCount(text: string | undefined, count: number): string | undefined {
    const grouped = groupSummaryLines(text);
    if (!grouped) return undefined;
    if (!count) return grouped;
    const lines = grouped.split("\n").filter((line) => {
        const match = line.match(/^\((\d+)\)/);
        return !match || Number(match[1]) <= count;
    });
    return lines.join("\n") || undefined;
}

function summaryTagNarrative(
    tags: ReportSummaryTag[],
    category: string,
    tag: string,
    periodTags: PeriodSummaryRecord[] = [],
): string | undefined {
    const cat = norm(category);
    const themes = themesInCategory(tags, category);
    const texts: string[] = [];
    for (const row of themes) {
        if (row.summary_status === "error" && !displayBody(row.ai_summary)) continue;
        const fromPeriod = periodNarrative(periodTags, row.feedback_category || category, row.feedback_tag || tag);
        const text = alignSummaryCount(
            groupSummaryLines(fromPeriod || displayBody(row.ai_summary)),
            row.feedback_count || 0,
        );
        if (text && text !== "Updating…" && !texts.includes(text)) texts.push(text);
    }
    if (texts.length) return groupSummaryLines(texts.join("\n"));
    const fromCounts =
        tags.find((row) => norm(row.feedback_category) === cat && labelsOverlap(row.feedback_tag, tag)) ||
        tags.find((row) => labelsOverlap(row.feedback_tag, tag));
    if (fromCounts?.summary_status === "error") return "Updating…";
    const fromPeriod = periodNarrative(periodTags, category, tag, undefined, true);
    return fromPeriod || displayBody(fromCounts?.ai_summary) || undefined;
}

function periodSentiment(period?: PeriodSummaryRecord): string | undefined {
    const raw = period?.highlights?.sentiment;
    return typeof raw === "string" && raw.trim() ? raw.trim() : undefined;
}

function summaryTagSentiment(
    tags: ReportSummaryTag[],
    category: string,
    tag: string,
    periodTags: PeriodSummaryRecord[] = [],
): string | undefined {
    const cat = norm(category);
    const fromThemes = majoritySentiment(themesInCategory(tags, category).map((row) => row.sentiment));
    if (fromThemes) return fromThemes;
    const fromPeriod =
        periodTags.find(
            (row) =>
                labelsOverlap(row.grain_label || row.grain_key, tag) &&
                (!cat || (row.grain_key || "").toLowerCase().includes(cat) || labelsOverlap(row.grain_label, tag)),
        ) || periodTags.find((row) => labelsOverlap(row.grain_label || row.grain_key, tag));
    return periodSentiment(fromPeriod);
}

export function buildProductRowsFromCounts(
    drill: DrillScope,
    items: ReportProductCount[],
    periodProducts: PeriodSummaryRecord[] = [],
    periodTags: PeriodSummaryRecord[] = [],
): MatrixRow[] {
    return items
        .filter((item) => (item.feedback_count || 0) > 0)
        .map((item) => {
        const product = display(item.product_name) || NO_PRODUCT_LABEL;
        const tagName = drill.feedback_tag || drill.feedback_category;
        const tagRows = tagName
            ? periodRowsForTag(periodTags, drill.feedback_category || tagName, tagName, product, true)
            : [];
        const period = tagRows[0] || (tagName
            ? undefined
            : periodProducts.find(
                (row) =>
                    norm(row.grain_label) === norm(product) ||
                    norm(row.grain_key) === norm(product) ||
                    (row.grain_key || "").split("::").includes(product),
            ));
        const tagText = tagName
            ? periodNarrative(periodTags, drill.feedback_category || tagName, tagName, product, true)
            : undefined;
        const narrative = tagName
            ? tagText === "Updating…"
                ? tagText
                : summaryFitsCount(tagText, item.feedback_count || 0)
            : period?.status === "error"
                ? "Updating…"
                : summaryFitsCount(displayBody(period?.summary_text), item.feedback_count || 0);
        return {
            kind: "data" as const,
            feedback_group: drill.group,
            product_name: product,
            feedback_category: drill.feedback_category,
            feedback_tag: drill.feedback_tag,
            feedback_count: item.feedback_count || null,
            feedback_summary_ai: alignSummaryCount(narrative, item.feedback_count || 0) || undefined,
            sentiment: periodSentiment(period),
            drill: {
                group: drill.group,
                level: drill.feedback_sub_tag ? "sub_tag" : drill.feedback_tag ? "tag" : "product",
                product_name: product,
                feedback_category: drill.feedback_category,
                feedback_tag: drill.feedback_tag,
                feedback_sub_tag: drill.feedback_sub_tag,
            },
        };
    })
        .filter((row) => Boolean(row.feedback_summary_ai));
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
            sentiment: display(row.sentiment_label) || undefined,
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
    // The matrix row's Feedback Tag is the level-2 name, and that same name is
    // stored on the fact view as feedback_category. feedback_tag on the view is
    // the theme. Filtering both columns by the level-2 name returns no rows.
    const category = categoryForTagDrill(drill.feedback_category, drill.feedback_tag);
    const tag = drill.feedback_tag;
    const tagNamesTheCategory = Boolean(tag) && norm(tag) === norm(category);
    return {
        ...base,
        feedback_group: drill.group,
        product_name: drill.product_name || base.product_name,
        feedback_category: category,
        feedback_tag: tagNamesTheCategory ? undefined : tag,
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
            sentiment: display(row.sentiment_label) || undefined,
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
    return columnsForSummaryTags();
}

export function columnsForSummaryTags(): MatrixColumn[] {
    return ["feedback_summary_ai", "feedback_category", "feedback_tag", "feedback_count", "sentiment"];
}

export function columnsForSummaryItems(): MatrixColumn[] {
    return ["sentiment", "feedback_summary_ai", "feedback_excerpt"];
}

export function columnsForProductDrill(drill: DrillScope): MatrixColumn[] {
    const cols: MatrixColumn[] = ["product_name", "feedback_summary_ai"];
    if (drill.level === "group" || drill.level === "category" || !drill.feedback_tag) {
        cols.push("feedback_category", "feedback_tag");
    }
    cols.push("feedback_count", "sentiment");
    return cols;
}

export function columnsForDetail(
    drill: DrillScope,
    includeProduct: boolean,
    verbatim = false,
): MatrixColumn[] {
    const cols: MatrixColumn[] = [];
    if (includeProduct && !drill.product_name) cols.push("product_name");
    if (!verbatim && !drill.feedback_category) cols.push("feedback_category");
    if (!drill.feedback_tag) cols.push("feedback_tag");
    if (verbatim) {
        cols.push("sentiment", "feedback_summary_ai", "feedback_excerpt", "call_datetime", "full_conversation");
        return cols;
    }
    cols.push(
        "sentiment",
        "feedback_summary_ai",
        "feedback_excerpt",
        "call_datetime",
        "full_conversation",
        "file_name",
        "audio",
    );
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
            sentiment: display(row.sentiment_label) || undefined,
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
    const parts: string[] = [];
    if (drill.product_name) parts.push(drill.product_name);
    if (drill.feedback_category) parts.push(drill.feedback_category);
    if (drill.feedback_tag && norm(drill.feedback_tag) !== norm(drill.feedback_category)) {
        parts.push(drill.feedback_tag);
    }
    return parts.length ? parts : [drillTitle(drill)];
}
