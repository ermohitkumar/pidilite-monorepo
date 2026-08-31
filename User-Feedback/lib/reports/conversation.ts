export type ChatSide = "left" | "right";

export type ConversationTurn = {
    speaker: string;
    text: string;
    side: ChatSide;
};

const SPEAKER_LABEL = String.raw`Speaker\s+\d+|FME|User|Dealer|Contractor|Customer|Carpenter`;
const TURN_RE = new RegExp(
    String.raw`(^|\n)\s*(?:\*{1,2})?\s*(${SPEAKER_LABEL})\s*[:\-–—]\s*(?:\*{1,2})?\s*`,
    "gi",
);

const KNOWN_SPEAKERS: Record<string, string> = {
    fme: "FME",
    user: "User",
    dealer: "Dealer",
    contractor: "Contractor",
    customer: "Customer",
    carpenter: "Carpenter",
};

function numberedSpeaker(raw: string): string | null {
    const match = /^speaker\s+(\d+)$/i.exec(raw);
    return match?.[1] ?? null;
}

function normalizeSpeaker(raw: string): string {
    const cleaned = raw.replaceAll("*", "").replace(/\s+/g, " ").trim();
    const numbered = numberedSpeaker(cleaned);
    if (numbered === "1") return "FME";
    if (numbered === "2") return "User";
    if (numbered) return `Speaker ${numbered}`;
    const key = cleaned.toLowerCase();
    if (key === "fme") return "FME";
    if (key in KNOWN_SPEAKERS) return "User";
    return cleaned;
}

function sideFor(speaker: string): ChatSide {
    const numbered = numberedSpeaker(speaker);
    if (numbered) return Number(numbered) % 2 === 1 ? "right" : "left";
    if (speaker === "FME") return "right";
    return "left";
}

function stripSurroundingMarkup(value: string): string {
    let start = 0;
    let end = value.length;
    while (start < end && (value[start] === "*" || value[start] === " ")) start += 1;
    while (end > start && (value[end - 1] === "*" || value[end - 1] === " ")) end -= 1;
    return value.slice(start, end).trim();
}

export function parseConversationTurns(raw: string): ConversationTurn[] {
    const text = (raw || "").replaceAll("\u00a0", " ").replaceAll("\r\n", "\n").trim();
    if (!text) return [];

    TURN_RE.lastIndex = 0;
    const matches = [...text.matchAll(TURN_RE)];
    if (matches.length === 0) return [];
    if (matches.length === 1 && (matches[0].index ?? 0) > 80) return [];

    const turns: ConversationTurn[] = [];
    for (let index = 0; index < matches.length; index += 1) {
        const match = matches[index];
        const speaker = normalizeSpeaker(match[2] || "");
        const start = (match.index ?? 0) + match[0].length;
        const end = index + 1 < matches.length ? (matches[index + 1].index ?? text.length) : text.length;
        const body = stripSurroundingMarkup(text.slice(start, end));
        if (!speaker || !body) continue;
        turns.push({ speaker, text: body, side: sideFor(speaker) });
    }
    return turns;
}

export function isFullConversationTitle(title?: string | null): boolean {
    return (title || "").trim().toLowerCase() === "full conversation";
}

export type TextRange = {
    start: number;
    end: number;
};

export type ExcerptHit = {
    turnIndex: number;
    range: TextRange | null;
    ranges: TextRange[];
    complete: boolean;
};

function foldChar(ch: string): string | null {
    if (ch === "\u00a0") return " ";
    if (/[A-Z]/.test(ch)) return ch.toLowerCase();
    if ("’‘`".includes(ch)) return "'";
    if ('“”'.includes(ch)) return '"';
    if ("–—-".includes(ch)) return " ";
    if (/[a-z0-9\u0900-\u097f']/.test(ch)) return ch;
    if (/\s/.test(ch)) return " ";
    return " ";
}

function foldWithMap(original: string): { folded: string; map: number[] } {
    let folded = "";
    const map: number[] = [];
    let lastSpace = true;
    for (let index = 0; index < original.length; index += 1) {
        const next = foldChar(original[index] || "");
        if (next === null) continue;
        if (next === " ") {
            if (lastSpace || folded.length === 0) continue;
            lastSpace = true;
            folded += " ";
            map.push(index);
            continue;
        }
        lastSpace = false;
        folded += next;
        map.push(index);
    }
    return { folded: folded.trimEnd(), map };
}

function originalRange(map: number[], folded: TextRange): TextRange | null {
    if (folded.start >= map.length) return null;
    const start = map[folded.start] ?? 0;
    const last = map[Math.min(folded.end, map.length) - 1] ?? start;
    return { start, end: last + 1 };
}

type FoldedTurn = {
    turnIndex: number;
    folded: string;
    map: number[];
};

type LocatedWord = {
    word: string;
    start: number;
    end: number;
    turnIndex: number;
};

function wordsWithSpans(folded: string): { word: string; start: number; end: number }[] {
    const words: { word: string; start: number; end: number }[] = [];
    const pattern = /\S+/g;
    let match: RegExpExecArray | null = pattern.exec(folded);
    while (match) {
        words.push({
            word: match[0],
            start: match.index,
            end: match.index + match[0].length,
        });
        match = pattern.exec(folded);
    }
    return words;
}

function mergeRanges(ranges: TextRange[]): TextRange[] {
    const sorted = [...ranges].filter((range) => range.end > range.start).sort((a, b) => a.start - b.start);
    const merged: TextRange[] = [];
    for (const range of sorted) {
        const last = merged[merged.length - 1];
        if (!last || range.start > last.end + 1) {
            merged.push({ ...range });
            continue;
        }
        last.end = Math.max(last.end, range.end);
    }
    return merged;
}

function pushHit(
    byTurn: Map<number, { ranges: TextRange[]; complete: boolean }>,
    turnIndex: number,
    range: TextRange | null,
    complete: boolean,
) {
    if (!range || range.end <= range.start) return;
    const current = byTurn.get(turnIndex) || { ranges: [], complete: false };
    current.ranges.push(range);
    current.complete = current.complete || complete;
    byTurn.set(turnIndex, current);
}

function hitsFromMap(byTurn: Map<number, { ranges: TextRange[]; complete: boolean }>): ExcerptHit[] {
    return [...byTurn.entries()]
        .sort((a, b) => a[0] - b[0])
        .map(([turnIndex, item]) => {
            const ranges = mergeRanges(item.ranges);
            return {
                turnIndex,
                range: ranges[0] || null,
                ranges,
                complete: item.complete,
            };
        });
}

function locateExactNeedle(foldedTurns: FoldedTurn[], needle: string): ExcerptHit[] {
    const byTurn = new Map<number, { ranges: TextRange[]; complete: boolean }>();
    let joined = "";
    const joinMap: { turnIndex: number; foldIndex: number }[] = [];
    for (const turn of foldedTurns) {
        if (!turn.folded) continue;
        if (joined.length > 0) {
            joined += " ";
            joinMap.push({ turnIndex: turn.turnIndex, foldIndex: -1 });
        }
        for (let index = 0; index < turn.folded.length; index += 1) {
            joined += turn.folded[index];
            joinMap.push({ turnIndex: turn.turnIndex, foldIndex: index });
        }
    }
    if (!joined) return [];

    let from = 0;
    let found = false;
    while (from <= joined.length - needle.length) {
        const at = joined.indexOf(needle, from);
        if (at < 0) break;
        found = true;
        const end = at + needle.length;
        for (const turn of foldedTurns) {
            const turnStart = joinMap.findIndex((item) => item.turnIndex === turn.turnIndex && item.foldIndex === 0);
            if (turnStart < 0) continue;
            const overlapStart = Math.max(at, turnStart);
            const overlapEnd = Math.min(end, turnStart + turn.folded.length);
            if (overlapEnd <= overlapStart) continue;
            let startIndex = overlapStart;
            let endIndex = overlapEnd - 1;
            while (startIndex <= endIndex && (joinMap[startIndex]?.foldIndex ?? -1) < 0) startIndex += 1;
            while (endIndex >= startIndex && (joinMap[endIndex]?.foldIndex ?? -1) < 0) endIndex -= 1;
            if (endIndex < startIndex) continue;
            const foldedRange = {
                start: joinMap[startIndex]?.foldIndex ?? 0,
                end: (joinMap[endIndex]?.foldIndex ?? 0) + 1,
            };
            if (foldedRange.start < 0 || foldedRange.end <= foldedRange.start) continue;
            pushHit(byTurn, turn.turnIndex, originalRange(turn.map, foldedRange), true);
        }
        from = at + Math.max(needle.length, 1);
    }
    return found ? hitsFromMap(byTurn) : [];
}

function expandToSentences(text: string, range: TextRange): TextRange {
    let start = range.start;
    let end = range.end;
    while (start > 0 && !".!?".includes(text[start - 1] || "")) start -= 1;
    while (start < end && /\s/.test(text[start] || "")) start += 1;
    while (end < text.length && !".!?".includes(text[end - 1] || "")) end += 1;
    return { start, end };
}

function locateWordRuns(
    foldedTurns: FoldedTurn[],
    needleWords: string[],
    turns: ConversationTurn[],
): ExcerptHit[] {
    if (needleWords.length === 0) return [];
    const hay: LocatedWord[] = [];
    for (const turn of foldedTurns) {
        for (const span of wordsWithSpans(turn.folded)) {
            hay.push({ ...span, turnIndex: turn.turnIndex });
        }
    }
    if (hay.length === 0) return [];

    const minRun = needleWords.length <= 2 ? needleWords.length : 3;
    const byTurn = new Map<number, { ranges: TextRange[]; complete: boolean }>();
    let hayFrom = 0;
    let needleFrom = 0;
    let matchedWords = 0;

    while (needleFrom < needleWords.length) {
        let best = { count: 0, hayAt: -1 };
        for (let hayIndex = hayFrom; hayIndex < hay.length; hayIndex += 1) {
            let count = 0;
            while (
                hayIndex + count < hay.length &&
                needleFrom + count < needleWords.length &&
                hay[hayIndex + count]?.word === needleWords[needleFrom + count]
            ) {
                count += 1;
            }
            if (count > best.count) {
                best = { count, hayAt: hayIndex };
                if (count === needleWords.length - needleFrom) break;
            }
        }
        if (best.count >= minRun && best.hayAt >= 0) {
            const slice = hay.slice(best.hayAt, best.hayAt + best.count);
            for (const turn of foldedTurns) {
                const words = slice.filter((word) => word.turnIndex === turn.turnIndex);
                if (words.length === 0) continue;
                const foldedRange = {
                    start: words[0].start,
                    end: words[words.length - 1].end,
                };
                const complete = best.count === needleWords.length && needleFrom === 0;
                pushHit(byTurn, turn.turnIndex, originalRange(turn.map, foldedRange), complete);
            }
            matchedWords += best.count;
            hayFrom = best.hayAt + best.count;
            needleFrom += best.count;
            continue;
        }
        needleFrom += 1;
    }

    if (matchedWords === 0) return [];
    const covering = new Map<number, { ranges: TextRange[]; complete: boolean }>();
    for (const [turnIndex, item] of byTurn) {
        const merged = mergeRanges(item.ranges);
        if (merged.length === 0) continue;
        const cover = expandToSentences(
            turns[turnIndex]?.text || "",
            { start: merged[0].start, end: merged[merged.length - 1].end },
        );
        const matchedChars = merged.reduce((sum, range) => sum + (range.end - range.start), 0);
        const span = cover.end - cover.start;
        const tight = span > 0 && matchedChars / span >= 0.5;
        if (merged.length === 1 || tight) {
            covering.set(turnIndex, { ranges: [cover], complete: true });
        } else {
            covering.set(turnIndex, { ranges: merged, complete: false });
        }
    }
    return hitsFromMap(covering);
}

export function matchExcerptInTurns(turns: ConversationTurn[], excerpt?: string | null): ExcerptHit[] {
    const needle = (excerpt || "").trim();
    if (!needle || turns.length === 0) return [];

    const needleFold = foldWithMap(needle).folded;
    if (!needleFold) return [];

    const foldedTurns: FoldedTurn[] = turns.map((turn, turnIndex) => {
        const folded = foldWithMap(turn.text);
        return { turnIndex, folded: folded.folded, map: folded.map };
    });

    const exact = locateExactNeedle(foldedTurns, needleFold);
    if (exact.length > 0) return exact;

    const needleWords = needleFold.split(" ").filter(Boolean);
    return locateWordRuns(foldedTurns, needleWords, turns);
}
