import type { PeriodSummaryRecord } from "@/lib/reports/types";

export type SummaryBlock =
    | { type: "heading"; text: string }
    | { type: "paragraph"; text: string }
    | { type: "list"; items: string[] };

export type ParsedSummary = {
    blocks: SummaryBlock[];
    themes: string[];
    products: string[];
    risks: string[];
};

const LABEL_RE = /^(themes|products|risks)\s*:\s*(.*)$/i;
const MD_HEADER_RE = /^#{1,3}\s+(.+)$/;
const BULLET_RE = /^(?:[-*•]|[0-9]+[.)])\s+(.+)$/;

function splitCsv(value: string): string[] {
    return value
        .split(/[,;•|/]+/)
        .map((part) => part.trim())
        .filter((part) => part.length > 1);
}

function splitSentences(text: string): string[] {
    const compact = text.replace(/\s+/g, " ").trim();
    if (!compact) return [];
    if (compact.length < 140) return [compact];
    const parts = compact.split(/(?<=[.!?])\s+(?=[A-Z])/).map((part) => part.trim()).filter(Boolean);
    return parts.length > 1 ? parts : [compact];
}

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

export function parseSummaryText(
    text?: string | null,
    highlights?: PeriodSummaryRecord["highlights"],
): ParsedSummary {
    const themes = [...((highlights?.themes as string[] | undefined) || [])];
    const products = [...((highlights?.products as string[] | undefined) || [])];
    const risks = [...((highlights?.risks as string[] | undefined) || [])];
    const blocks: SummaryBlock[] = [];
    let list: string[] = [];

    const flushList = () => {
        if (!list.length) return;
        blocks.push({ type: "list", items: unique(list) });
        list = [];
    };

    for (const raw of (text || "").replaceAll("\r\n", "\n").split(/\n+/)) {
        const line = raw.replaceAll("\u00a0", " ").replace(/\s+/g, " ").trim();
        if (!line) continue;
        const labeled = line.match(LABEL_RE);
        if (labeled) {
            flushList();
            const kind = labeled[1].toLowerCase();
            const values = splitCsv(labeled[2]);
            if (kind === "themes") themes.push(...values);
            else if (kind === "products") products.push(...values);
            else risks.push(...values);
            continue;
        }
        const heading = line.match(MD_HEADER_RE);
        if (heading) {
            flushList();
            blocks.push({ type: "heading", text: heading[1].trim() });
            continue;
        }
        const titled = line.match(/^(.{2,80}):$/);
        if (titled && !line.includes(".")) {
            flushList();
            blocks.push({ type: "heading", text: titled[1].trim() });
            continue;
        }
        const bullet = line.match(BULLET_RE);
        if (bullet) {
            list.push(bullet[1].trim());
            continue;
        }
        flushList();
        for (const sentence of splitSentences(line)) {
            blocks.push({ type: "paragraph", text: sentence });
        }
    }
    flushList();

    return {
        blocks,
        themes: unique(themes),
        products: unique(products),
        risks: unique(risks),
    };
}

function ChipRow({ label, items }: { label: string; items: string[] }) {
    if (!items.length) return null;
    return (
        <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500">{label}</p>
            <div className="mt-1.5 flex flex-wrap gap-1.5">
                {items.map((item) => (
                    <span
                        key={`${label}-${item}`}
                        className="rounded-full border border-slate-200 bg-white px-2.5 py-1 text-xs text-slate-700"
                    >
                        {item}
                    </span>
                ))}
            </div>
        </div>
    );
}

export function FormattedSummary({
    text,
    highlights,
    emptyLabel = "No summary.",
}: {
    text?: string | null;
    highlights?: PeriodSummaryRecord["highlights"];
    emptyLabel?: string;
}) {
    const parsed = parseSummaryText(text, highlights);
    if (!parsed.blocks.length && !parsed.themes.length && !parsed.products.length && !parsed.risks.length) {
        return <p className="text-sm text-slate-500">{emptyLabel}</p>;
    }
    return (
        <div className="space-y-4">
            {parsed.blocks.length ? (
                <div className="space-y-3">
                    {parsed.blocks.map((block, index) => {
                        if (block.type === "heading") {
                            return (
                                <h4 key={`h-${index}`} className="text-sm font-semibold text-slate-900">
                                    {block.text}
                                </h4>
                            );
                        }
                        if (block.type === "list") {
                            return (
                                <ul key={`l-${index}`} className="list-disc space-y-1.5 pl-5 text-sm leading-6 text-slate-800">
                                    {block.items.map((item) => (
                                        <li key={item}>{item}</li>
                                    ))}
                                </ul>
                            );
                        }
                        return (
                            <p key={`p-${index}`} className="text-sm leading-7 text-slate-800">
                                {block.text}
                            </p>
                        );
                    })}
                </div>
            ) : null}
            <ChipRow label="Themes" items={parsed.themes} />
            <ChipRow label="Products" items={parsed.products} />
            <ChipRow label="Risks" items={parsed.risks} />
        </div>
    );
}
