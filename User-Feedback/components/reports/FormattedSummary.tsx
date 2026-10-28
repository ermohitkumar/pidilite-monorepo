import type { PeriodSummaryRecord } from "@/lib/reports/types";

export type SummaryPoint = {
    theme?: string;
    line: string;
    detail?: string;
    summary?: string;
    user_count?: number;
    sentiment?: string;
};

export type SummaryFinding = {
    title: string;
    product?: string;
    points?: SummaryPoint[];
    summary?: string;
    quotes?: string[];
    user_count?: number;
    sentiment?: string;
};

function narrativeFromData(value?: string): string {
    const raw = (value || "").trim();
    if (!raw) return "";
    const pattern = raw.match(/pattern:\s*(.*)$/i);
    if (pattern?.[1]) return pattern[1].trim();
    if (/^\d+\s+unique contractor/i.test(raw)) return "";
    return raw;
}

export type SummaryBlock =
    | { type: "heading"; text: string }
    | { type: "paragraph"; text: string }
    | { type: "list"; items: string[] };

export type ParsedSummary = {
    blocks: SummaryBlock[];
    findings: SummaryFinding[];
};

const LABEL_RE = /^(themes|products|risks)\s*:\s*(.*)$/i;
const MD_HEADER_RE = /^#{1,3}\s+(.+)$/;
const BULLET_RE = /^(?:[-*•]|[0-9]+[.)])\s+(.+)$/;
const NUMBERED_RE = /^(\d+)\.\s+(.+)$/;
const COUNT_PREFIX_RE = /^(\d+)\s+users?\b/i;
const COUNT_SUFFIX_RE = /\((\d+)\s+users?\)\.?$/i;
const TRUNCATED_TAIL_RE = /\b(of|the|a|an|and|or|to|for|with|is|are|was|were|has|have|instead|but|without|from|into|onto|over|under|than)$/i;

function unique(items: string[]): string[] {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const item of items) {
        const key = item.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        out.push(item);
    }
    return out;
}

function looksTruncated(value: string): boolean {
    const text = value.trim();
    if (!text) return true;
    if (text.endsWith("…") || text.endsWith("...")) return true;
    if (TRUNCATED_TAIL_RE.test(text)) return true;
    // Product-strip mangling: "the quality of is good"
    if (/\bof\s+(?:is|has|was|are)\b/i.test(text)) return true;
    return false;
}

function firstSentence(value: string): string {
    let cleaned = value.replace(/\s+/g, " ").trim();
    if (!cleaned) return "";
    cleaned = cleaned.replace(
        /^(?:noted:\s*)?(?:the\s+)?users?\s+(?:praises|states?|suggests|experienced|has|have|likes?|appreciates|mentions|reports?|said|says|finds?|found|prefers?)\s+/i,
        "",
    );
    const match = cleaned.match(/^(.+?[.!?])(?:\s|$)/);
    return (match?.[1] || cleaned).trim().replace(/\.+$/, "");
}

function isOthersTheme(value: string): boolean {
    return value.replace(/\s+/g, " ").trim().toLowerCase() === "others";
}

function othersLast(keys: string[]): string[] {
    return [...keys].sort((left, right) => Number(isOthersTheme(left)) - Number(isOthersTheme(right)));
}

type PointDisplay = {
    lead: string;
    body: string;
    separator: "" | " " | " — ";
};

function sentenceCase(value: string): string {
    const text = value.trim();
    if (!text) return "";
    return text[0].toUpperCase() + text.slice(1);
}

function pointBody(point: SummaryPoint): string {
    const detail = String(point.detail || "").trim();
    const summary = String(point.summary || "").trim();
    const line = String(point.line || "").trim();
    let body = "";
    if (summary && (!detail || looksTruncated(detail) || summary.length > detail.length + 12)) {
        body = firstSentence(summary);
    } else if (detail && !looksTruncated(detail)) {
        body = detail;
    } else if (detail) {
        body = detail.replace(/\bof\s+(?=is\b|has\b|was\b|are\b)/gi, "").replace(/\s+/g, " ").trim();
    } else if (line.includes(" — ")) {
        body = line.split(" — ").slice(1).join(" — ").trim().replace(COUNT_SUFFIX_RE, "").trim();
    }
    return body.replace(COUNT_SUFFIX_RE, "").trim();
}

const PAREN_COUNT_RE = /^\((\d+)\)\s+(.+)$/;

/** (1) Theme - detail. Same string in the cell and in View more. */
export function pointDisplay(point: SummaryPoint): PointDisplay {
    const line = String(point.line || "").trim();
    const parsedCount = line.match(PAREN_COUNT_RE) || line.match(COUNT_SUFFIX_RE) || line.match(COUNT_PREFIX_RE);
    const count = Math.max(Number(point.user_count || 0), parsedCount ? Number(parsedCount[1]) : 0);
    let themeLabel = sentenceCase(String(point.theme || "").trim());
    let body = pointBody(point);
    if (!themeLabel && line.includes(" — ")) {
        const [left, ...rest] = line.replace(COUNT_SUFFIX_RE, "").replace(PAREN_COUNT_RE, "$2").split(" — ");
        themeLabel = sentenceCase(left.trim());
        if (!body) body = rest.join(" — ").trim();
    }
    if (!themeLabel && line.includes(" - ") && PAREN_COUNT_RE.test(line)) {
        const rest = line.replace(PAREN_COUNT_RE, "$2");
        const [left, ...tail] = rest.split(" - ");
        themeLabel = sentenceCase(left.trim());
        if (!body) body = tail.join(" - ").trim();
    }
    const prefix = count >= 1 ? `(${count})` : "";
    if (prefix && themeLabel && body && body.toLowerCase() !== themeLabel.toLowerCase()) {
        return { lead: "", body: `${prefix} ${themeLabel} - ${body}`, separator: "" };
    }
    if (prefix && themeLabel) return { lead: "", body: `${prefix} ${themeLabel}`, separator: "" };
    if (prefix && body) return { lead: "", body: `${prefix} ${sentenceCase(body)}`, separator: "" };
    if (line) return { lead: "", body: line, separator: "" };
    return { lead: "", body: body, separator: "" };
}

const SUMMARY_LINE_RE = /^\((\d+)\)\s+(.+)$/;

function cleanProduct(value?: string | null): string {
    const text = (value || "").trim();
    if (!text || text.toLowerCase() === "other" || text.toLowerCase() === "unknown") return "";
    return text;
}

function parseSummaryLine(line: string): { count: number; label: string; detail: string } {
    const match = line.match(SUMMARY_LINE_RE);
    if (!match) return { count: 0, label: line.trim(), detail: "" };
    const rest = match[2].trim();
    const dash = rest.indexOf(" - ");
    return {
        count: Number(match[1]) || 1,
        label: (dash >= 0 ? rest.slice(0, dash) : rest).trim(),
        detail: dash >= 0 ? rest.slice(dash + 3).trim() : "",
    };
}

/** One line per theme. Name the product only when the same issue is on more than one product. */
export function groupedFindingText(findings: SummaryFinding[]): string {
    const groups = new Map<string, { label: string; count: number; parts: Array<{ product: string; detail: string }> }>();
    const order: string[] = [];
    for (const finding of findings) {
        const product = cleanProduct(finding.product);
        for (const point of sortPoints(finding.points || [])) {
            const formatted = formatPointLine(point);
            if (!formatted) continue;
            const parsed = parseSummaryLine(formatted);
            const theme = sentenceCase(String(point.theme || "").trim()) || parsed.label;
            if (!theme) continue;
            const namedProduct = product && product.toLowerCase() !== theme.toLowerCase() ? product : "";
            const detail = String(point.detail || "").trim() || parsed.detail;
            const count = Math.max(Number(point.user_count || 0), parsed.count || 0) || 1;
            const key = theme.toLowerCase();
            const bucket = groups.get(key);
            if (!bucket) {
                groups.set(key, { label: theme, count, parts: detail ? [{ product: namedProduct, detail }] : [] });
                order.push(key);
                continue;
            }
            bucket.count += count;
            if (detail && !bucket.parts.some((part) => part.product.toLowerCase() === namedProduct.toLowerCase() && part.detail.toLowerCase() === detail.toLowerCase())) {
                bucket.parts.push({ product: namedProduct, detail });
            }
        }
    }
    return othersLast(order)
        .map((key) => {
            const bucket = groups.get(key);
            if (!bucket) return "";
            const products = new Set(bucket.parts.map((part) => part.product).filter(Boolean));
            const detail = bucket.parts
                .map((part) => (products.size > 1 && part.product ? `${part.product}: ${part.detail}` : part.detail))
                .join("; ");
            return detail ? `(${bucket.count}) ${bucket.label} - ${detail}` : `(${bucket.count}) ${bucket.label}`;
        })
        .filter(Boolean)
        .join("\n");
}

/** Same lines the table cell and View more both show. */
export function summaryDisplayText(
    text?: string | null,
    highlights?: PeriodSummaryRecord["highlights"],
): string {
    const parsed = parseSummaryText(text, highlights);
    if (parsed.findings.length) return groupedFindingText(parsed.findings);
    const lines: string[] = [];
    for (const block of parsed.blocks) {
        if (block.type === "heading") continue;
        if (block.type === "list") {
            for (const item of block.items) {
                const line = formatPointLine({ line: item, user_count: 1 });
                if (line) lines.push(line);
            }
            continue;
        }
        if (block.text.trim()) lines.push(block.text.trim());
    }
    return groupSummaryLines(lines.join("\n"));
}

/** Collapse repeated themes into one line. Several products stay in that one line. */
export function groupSummaryLines(text?: string | null): string {
    const groups = new Map<string, { label: string; count: number; details: string[] }>();
    const order: string[] = [];
    for (const raw of (text || "").split(/\n+/)) {
        const line = raw.replaceAll("\u00a0", " ").trim();
        if (!line) continue;
        const match = line.match(SUMMARY_LINE_RE);
        if (!match) {
            const key = line.toLowerCase();
            if (!groups.has(key)) {
                groups.set(key, { label: line, count: 0, details: [] });
                order.push(key);
            }
            continue;
        }
        const count = Number(match[1]) || 1;
        const rest = match[2].trim();
        const dash = rest.indexOf(" - ");
        const label = (dash >= 0 ? rest.slice(0, dash) : rest).trim();
        const detail = dash >= 0 ? rest.slice(dash + 3).trim() : "";
        const key = label.toLowerCase();
        const bucket = groups.get(key);
        if (!bucket) {
            groups.set(key, { label, count, details: detail ? [detail] : [] });
            order.push(key);
            continue;
        }
        bucket.count += count;
        if (detail && !bucket.details.some((seen) => seen.toLowerCase() === detail.toLowerCase())) {
            bucket.details.push(detail);
        }
    }
    return othersLast(order)
        .map((key) => {
            const bucket = groups.get(key);
            if (!bucket) return "";
            if (!bucket.count) return bucket.label;
            const detail = bucket.details.join("; ");
            return detail ? `(${bucket.count}) ${bucket.label} - ${detail}` : `(${bucket.count}) ${bucket.label}`;
        })
        .filter(Boolean)
        .join("\n");
}

/** Count first, then the theme and detail. */
export function formatPointLine(point: SummaryPoint): string {
    const display = pointDisplay(point);
    return `${display.lead}${display.separator}${display.body}`.trim();
}

function sortPoints(points: SummaryPoint[]): SummaryPoint[] {
    return [...points].sort((left, right) => {
        const others = Number(isOthersTheme(left.theme || "")) - Number(isOthersTheme(right.theme || ""));
        if (others) return others;
        const count = Number(right.user_count || 0) - Number(left.user_count || 0);
        if (count) return count;
        return (left.theme || left.line || "").localeCompare(right.theme || right.line || "");
    });
}

function asPoints(
    raw: Array<{
        theme?: string;
        line?: string;
        summary?: string;
        detail?: string;
        user_count?: number;
        sentiment?: string;
    }> | undefined,
): SummaryPoint[] {
    return (raw || [])
        .map((point) => ({
            theme: String(point.theme || "").trim(),
            line: String(point.line || point.theme || point.summary || "").trim(),
            detail: String(point.detail || "").trim(),
            summary: String(point.summary || "").trim(),
            user_count: Number(point.user_count || 0),
            sentiment: String(point.sentiment || "").trim() || undefined,
        }))
        .filter((point) => point.line || point.theme || point.summary);
}

function findingsFromHighlights(highlights?: PeriodSummaryRecord["highlights"]): SummaryFinding[] {
    const raw = (highlights?.findings as Array<
        SummaryFinding & { data?: string; product?: string; points?: SummaryPoint[] }
    > | undefined) || [];
    return raw
        .map((item) => {
            const title = String(item.product || item.title || "").trim();
            const points = asPoints(item.points);
            const summary = String(item.summary || "").trim() || narrativeFromData(item.data);
            if (!points.length && summary) {
                points.push({ line: summary, user_count: Number(item.user_count || 0) });
            }
            return {
                title,
                product: title,
                points,
                summary,
                quotes: (item.quotes || []).map((quote) => String(quote || "").trim()).filter(Boolean),
                user_count: Number(item.user_count || 0),
                sentiment: String(item.sentiment || "").trim() || undefined,
            };
        })
        .filter((item) => Boolean(item.points?.length) || Boolean(item.title && item.summary));
}

function parseFindingsFromText(text?: string | null): SummaryFinding[] {
    const findings: SummaryFinding[] = [];
    let current: SummaryFinding | null = null;

    const pushCurrent = () => {
        if (!current) return;
        if (!current.points?.length && current.summary) {
            current.points = [{ line: current.summary, user_count: current.user_count || 0 }];
        }
        if (current.points?.length) findings.push(current);
        current = null;
    };

    for (const raw of (text || "").replaceAll("\r\n", "\n").split("\n")) {
        const line = raw.replaceAll("\u00a0", " ").trim();
        if (!line) continue;
        if (LABEL_RE.test(line) || /^data:\s*/i.test(line)) continue;
        const numbered = line.match(NUMBERED_RE);
        if (numbered) {
            pushCurrent();
            current = { title: numbered[2].trim(), points: [], summary: "", quotes: [], user_count: 0 };
            continue;
        }
        const counted = line.match(PAREN_COUNT_RE);
        const bullet = line.match(BULLET_RE);
        const item = counted ? line : bullet ? bullet[1].trim() : "";
        if (item) {
            if (/^["“].+["”]$/.test(item)) continue;
            if (!current) current = { title: "", points: [], summary: "", quotes: [], user_count: 0 };
            current.points = current.points || [];
            const countMatch = item.match(PAREN_COUNT_RE) || item.match(COUNT_SUFFIX_RE) || item.match(COUNT_PREFIX_RE);
            current.points.push({
                line: item,
                user_count: countMatch ? Number(countMatch[1]) : 1,
            });
            continue;
        }
        const countLine = line.match(
            /^(\d+)\s+users? reported (?:this|similar) observations?\.?$/i,
        );
        if (countLine && current) {
            current.user_count = Number(countLine[1]);
            continue;
        }
        if (current && !current.points?.length && current.summary) {
            current.summary = [current.summary, line].filter(Boolean).join(" ");
            continue;
        }
        pushCurrent();
        current = { title: line, points: [], summary: "", quotes: [], user_count: 0 };
    }
    pushCurrent();
    return findings.filter((item) => item.title || item.points?.length);
}

export function parseSummaryText(
    text?: string | null,
    highlights?: PeriodSummaryRecord["highlights"],
): ParsedSummary {
    const findings = findingsFromHighlights(highlights);
    const blocks: SummaryBlock[] = [];
    let list: string[] = [];

    const flushList = () => {
        if (!list.length) return;
        blocks.push({ type: "list", items: unique(list) });
        list = [];
    };

    if (!findings.length) {
        const parsed = parseFindingsFromText(text);
        if (parsed.length) {
            return { blocks: [], findings: parsed };
        }
        for (const raw of (text || "").replaceAll("\r\n", "\n").split(/\n+/)) {
            const line = raw.replaceAll("\u00a0", " ").replace(/\s+/g, " ").trim();
            if (!line) continue;
            if (LABEL_RE.test(line) || /^data:\s*/i.test(line)) {
                flushList();
                continue;
            }
            const heading = line.match(MD_HEADER_RE);
            if (heading) {
                flushList();
                blocks.push({ type: "heading", text: heading[1].trim() });
                continue;
            }
            const bullet = line.match(BULLET_RE);
            if (bullet) {
                const item = bullet[1].trim();
                if (/^["“].+["”]$/.test(item)) {
                    continue;
                }
                list.push(item);
                continue;
            }
            flushList();
            blocks.push({ type: "paragraph", text: line });
        }
        flushList();
    }

    return {
        blocks,
        findings,
    };
}

function normalizeHeading(value: string): string {
    return value
        .replace(/^\d+\.\s*/, "")
        .replace(/[.“"]+$/g, "")
        .replace(/\.$/, "")
        .trim()
        .toLowerCase();
}

function collapseFindings(findings: SummaryFinding[]): SummaryFinding[] {
    const out: SummaryFinding[] = [];
    const index = new Map<string, number>();
    for (const item of findings) {
        const key = normalizeHeading(item.product || item.title);
        const existing = index.get(key);
        const points = asPoints(item.points);
        if (existing === undefined) {
            index.set(key, out.length);
            out.push({
                title: item.title,
                product: item.product || item.title,
                points,
                summary: item.summary || "",
                quotes: [...(item.quotes || [])],
                user_count: item.user_count || 0,
                sentiment: item.sentiment,
            });
            continue;
        }
        const target = out[existing];
        target.user_count = Number(target.user_count || 0) + Number(item.user_count || 0);
        const merged = target.points || [];
        for (const point of points) {
            const match = merged.find(
                (seen) =>
                    normalizeHeading(seen.line) === normalizeHeading(point.line) ||
                    (seen.theme && point.theme && normalizeHeading(seen.theme) === normalizeHeading(point.theme)),
            );
            if (match) {
                match.user_count = Number(match.user_count || 0) + Number(point.user_count || 0);
                if (!match.summary && point.summary) match.summary = point.summary;
                if ((!match.detail || looksTruncated(match.detail)) && point.detail && !looksTruncated(point.detail)) {
                    match.detail = point.detail;
                }
            } else {
                merged.push(point);
            }
        }
        target.points = merged;
    }
    return out;
}

function FindingList({
    findings,
}: {
    findings: SummaryFinding[];
    heading?: string;
    productHref?: (product: string) => string;
}) {
    const lines = groupedFindingText(collapseFindings(findings)).split("\n").filter(Boolean);
    if (!lines.length) return null;
    return (
        <div className="space-y-2 text-[17px] leading-7 text-slate-800">
            {lines.map((line) => (
                <p key={line} className="whitespace-pre-wrap break-words">
                    <HighlightedSummaryLine text={line} />
                </p>
            ))}
        </div>
    );
}

function HighlightedSummaryLine({ text }: { text: string }) {
    const match = text.match(/^(\(\d+\)\s+)(.+?)(?=\s+-\s+|$)([\s\S]*)$/);
    if (!match) return <>{text}</>;
    return (
        <>
            <span className="rounded bg-violet-100 px-1.5 py-0.5 font-semibold text-violet-900">
                {match[1]}{match[2]}
            </span>
            {match[3]}
        </>
    );
}

export function FormattedSummary({
    text,
    highlights,
    heading,
    emptyLabel = "No summary.",
    productHref,
}: {
    text?: string | null;
    highlights?: PeriodSummaryRecord["highlights"];
    heading?: string;
    emptyLabel?: string;
    productHref?: (product: string) => string;
}) {
    const parsed = parseSummaryText(text, highlights);
    if (!parsed.findings.length && !parsed.blocks.length) {
        return <p className="text-base text-slate-500">{emptyLabel}</p>;
    }
    return (
        <div className="space-y-4">
            {parsed.findings.length ? (
                <FindingList findings={parsed.findings} heading={heading} productHref={productHref} />
            ) : parsed.blocks.length ? (
                <div className="space-y-3">
                    {parsed.blocks.map((block, index) => {
                        if (block.type === "heading") {
                            return (
                                <h4 key={`h-${index}`} className="text-base font-semibold text-slate-900">
                                    {block.text}
                                </h4>
                            );
                        }
                        if (block.type === "list") {
                            return (
                                <ul key={`l-${index}`} className="list-disc space-y-1.5 pl-5 text-base leading-7 text-slate-800">
                                    {block.items.map((item) => (
                                        <li key={item} className="whitespace-pre-wrap break-words">
                                            <HighlightedSummaryLine text={item} />
                                        </li>
                                    ))}
                                </ul>
                            );
                        }
                        return (
                            <p key={`p-${index}`} className="whitespace-pre-wrap break-words text-base leading-7 text-slate-800">
                                <HighlightedSummaryLine text={block.text} />
                            </p>
                        );
                    })}
                </div>
            ) : null}
        </div>
    );
}
