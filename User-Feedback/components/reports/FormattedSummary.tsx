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

function softTheme(value: string): string {
    const text = value.trim().replace(/\.+$/, "");
    if (!text) return "";
    if (text[0] === text[0].toUpperCase() && text.slice(1) !== text.slice(1).toUpperCase()) {
        return text[0].toLowerCase() + text.slice(1);
    }
    return text;
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

function countTail(count: number): string {
    const noun = count === 1 ? "user" : "users";
    return `(${count} ${noun})`;
}

function sentenceCase(value: string): string {
    const text = value.trim();
    if (!text) return "";
    return text[0].toUpperCase() + text.slice(1);
}

/** Theme/detail first; user count trails the sentence. */
export function formatPointLine(point: SummaryPoint): string {
    const count = Math.max(Number(point.user_count || 0), 0);
    const theme = String(point.theme || "").trim();
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

    const themeLabel = softTheme(theme);
    const tail = count >= 1 ? ` ${countTail(count)}` : "";

    if (count >= 1) {
        if (
            body &&
            themeLabel &&
            body.toLowerCase() !== themeLabel.toLowerCase() &&
            !themeLabel.toLowerCase().includes(body.toLowerCase())
        ) {
            return `${sentenceCase(themeLabel)} — ${body}${tail}`;
        }
        if (body) return `${sentenceCase(body)}${tail}`;
        if (themeLabel) return `${sentenceCase(themeLabel)}${tail}`;
        if (COUNT_PREFIX_RE.test(line) || COUNT_SUFFIX_RE.test(line)) {
            const stripped = line
                .replace(COUNT_PREFIX_RE, "")
                .replace(/^\s*reported\s+/i, "")
                .replace(COUNT_SUFFIX_RE, "")
                .replace(/\s+—\s+/g, " — ")
                .trim();
            return stripped ? `${sentenceCase(stripped)}${tail}` : countTail(count);
        }
        return countTail(count);
    }

    if (COUNT_PREFIX_RE.test(line) || COUNT_SUFFIX_RE.test(line)) return line;
    return body || line;
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
        .filter((item) => item.title && (item.points?.length || item.summary));
}

function parseFindingsFromText(text?: string | null): SummaryFinding[] {
    const findings: SummaryFinding[] = [];
    let current: SummaryFinding | null = null;

    const pushCurrent = () => {
        if (!current) return;
        if (!current.points?.length && current.summary) {
            current.points = [{ line: current.summary, user_count: current.user_count || 0 }];
        }
        if (current.title && current.points?.length) findings.push(current);
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
        const bullet = line.match(BULLET_RE);
        if (bullet) {
            const item = bullet[1].trim();
            if (/^["“].+["”]$/.test(item)) continue;
            if (!current) current = { title: "", points: [], summary: "", quotes: [], user_count: 0 };
            current.points = current.points || [];
            const countMatch = item.match(COUNT_SUFFIX_RE) || item.match(COUNT_PREFIX_RE);
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

function headingMatches(findingTitle: string, cardTitle?: string): boolean {
    const finding = normalizeHeading(findingTitle);
    if (!finding || finding === "other" || finding === "unknown") return true;
    if (!cardTitle) return false;
    const card = normalizeHeading(cardTitle);
    return Boolean(card && (finding === card || finding.startsWith(`${card} —`) || card.startsWith(`${finding} —`)));
}

function FindingList({ findings, heading }: { findings: SummaryFinding[]; heading?: string }) {
    const items = collapseFindings(findings);
    const hideAllTitles = items.length === 1 && headingMatches(items[0].title, heading);
    return (
        <div className="space-y-6">
            {items.map((finding, index) => {
                const hideTitle = hideAllTitles || headingMatches(finding.title, heading);
                const points = finding.points || [];
                return (
                    <section
                        key={`${index}-${finding.title}`}
                        className={hideTitle ? "" : "border-t border-slate-200 pt-4 first:border-t-0 first:pt-0"}
                    >
                        {hideTitle ? null : (
                            <h4 className="mb-2 text-base font-semibold text-slate-900">
                                {finding.title}
                            </h4>
                        )}
                        {points.length ? (
                            <ul className="list-disc space-y-2 pl-5 text-base leading-7 text-slate-800">
                                {points.map((point, pointIndex) => {
                                    const display = formatPointLine(point);
                                    return (
                                        <li key={`${pointIndex}-${display}`} className="whitespace-pre-wrap break-words">
                                            {display}
                                        </li>
                                    );
                                })}
                            </ul>
                        ) : finding.summary ? (
                            <p className="whitespace-pre-wrap break-words text-base leading-7 text-slate-800">
                                {finding.summary}
                            </p>
                        ) : null}
                    </section>
                );
            })}
        </div>
    );
}

export function FormattedSummary({
    text,
    highlights,
    heading,
    emptyLabel = "No summary.",
}: {
    text?: string | null;
    highlights?: PeriodSummaryRecord["highlights"];
    heading?: string;
    emptyLabel?: string;
}) {
    const parsed = parseSummaryText(text, highlights);
    if (!parsed.findings.length && !parsed.blocks.length) {
        return <p className="text-base text-slate-500">{emptyLabel}</p>;
    }
    return (
        <div className="space-y-4">
            {parsed.findings.length ? (
                <FindingList findings={parsed.findings} heading={heading} />
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
                                            {item}
                                        </li>
                                    ))}
                                </ul>
                            );
                        }
                        return (
                            <p key={`p-${index}`} className="whitespace-pre-wrap break-words text-base leading-7 text-slate-800">
                                {block.text}
                            </p>
                        );
                    })}
                </div>
            ) : null}
        </div>
    );
}
