import { getBackendApiUrl } from "@/lib/auth/env";
import { canPlayAudio } from "@/lib/auth/permissions";
import { SESSION_COOKIE, getSession } from "@/lib/auth/session";
import { Storage } from "@google-cloud/storage";
import type { File } from "@google-cloud/storage";
import { NextRequest, NextResponse } from "next/server";
import { createReadStream, createWriteStream, type WriteStream } from "node:fs";
import { mkdtemp, rm } from "node:fs/promises";
import { Readable } from "node:stream";
import { tmpdir } from "node:os";
import { join } from "node:path";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 300;

const MAX_FILES = 5000;
const MAX_ARCHIVE_BYTES = 2 * 1024 * 1024 * 1024;
const GS_URI = /^gs:\/\/([a-z0-9][a-z0-9._-]{1,61}[a-z0-9])\/(.+)$/;
const utf8 = new TextEncoder();

type Job = { job_id: string; file_name?: string | null };
type Locator = { job_id: string; file_name?: string | null; gcs_uri: string };
type ArchiveEntry = { name: string; crc: number; size: number; offset: number };

const crcTable = (() => {
    const table = new Uint32Array(256);
    for (let index = 0; index < 256; index++) {
        let value = index;
        for (let bit = 0; bit < 8; bit++) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1;
        table[index] = value >>> 0;
    }
    return table;
})();

function crcUpdate(crc: number, data: Buffer): number {
    let value = crc;
    for (const byte of data) value = crcTable[(value ^ byte) & 0xff] ^ (value >>> 8);
    return value >>> 0;
}

function zipHeader(signature: number, size: number): Buffer {
    const buffer = Buffer.alloc(size);
    buffer.writeUInt32LE(signature, 0);
    return buffer;
}

async function write(stream: WriteStream, buffer: Buffer): Promise<void> {
    if (!stream.write(buffer)) await new Promise<void>((resolve, reject) => {
        stream.once("drain", resolve);
        stream.once("error", reject);
    });
}

function validDate(value: string | null): value is string {
    if (!value || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
    const date = new Date(`${value}T00:00:00.000Z`);
    return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

function safeName(name: string | null | undefined, jobId: string, index: number): string {
    const base = (name || "recording").split(/[\\/]/).pop()!.replace(/[\u0000-\u001f<>:"|?*]/g, "_").slice(0, 140);
    return `${String(index).padStart(4, "0")}_${jobId.slice(0, 8)}_${base || "recording"}`;
}

function headersFor(request: NextRequest): HeadersInit {
    const token = request.cookies.get(SESSION_COOKIE)?.value;
    const headers: Record<string, string> = { Accept: "application/json" };
    if (token) {
        headers.Authorization = `Bearer ${token}`;
        headers.Cookie = `${SESSION_COOKIE}=${token}`;
    }
    return headers;
}

async function fetchJobs(request: NextRequest, startDate: string, endDate: string): Promise<Job[]> {
    const jobs: Job[] = [];
    const backend = getBackendApiUrl();
    const headers = headersFor(request);
    for (let page = 1; page <= Math.ceil(MAX_FILES / 100) + 1; page++) {
        const params = new URLSearchParams({ page: String(page), size: "100", start_date: startDate, end_date: endDate });
        const response = await fetch(`${backend}/api/v1/dashboard/jobs?${params}`, { headers, cache: "no-store" });
        const json = await response.json().catch(() => null);
        if (!response.ok || !json?.success) throw new Error(json?.message || json?.detail || "Failed to list audio files");
        const items = json.data?.items;
        if (!Array.isArray(items)) throw new Error("Unexpected response while listing audio files");
        jobs.push(...items);
        if (jobs.length > MAX_FILES) throw Object.assign(new Error(`Date range exceeds the ${MAX_FILES.toLocaleString()} file limit. Narrow the date range.`), { status: 413 });
        if (!json.data?.metadata?.has_next || items.length === 0) break;
    }
    return jobs;
}

async function fetchLocator(request: NextRequest, jobId: string): Promise<Locator | null> {
    const response = await fetch(`${getBackendApiUrl()}/api/v1/reports/audio-locator?job_id=${encodeURIComponent(jobId)}`, {
        headers: headersFor(request), cache: "no-store",
    });
    const json = await response.json().catch(() => null);
    if (response.status === 404) return null;
    if (!response.ok || !json?.success || !json.data?.gcs_uri) {
        throw Object.assign(new Error(json?.message || json?.detail || "Failed to resolve an audio file"), { status: response.status === 401 || response.status === 403 ? response.status : 502 });
    }
    return json.data as Locator;
}

async function withConcurrency<T, R>(items: T[], concurrency: number, callback: (item: T) => Promise<R>): Promise<R[]> {
    const output = new Array<R>(items.length);
    let cursor = 0;
    await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, async () => {
        while (cursor < items.length) {
            const index = cursor++;
            output[index] = await callback(items[index]);
        }
    }));
    return output;
}

async function appendEntry(stream: WriteStream, file: File, name: string, offset: number): Promise<ArchiveEntry> {
    const filename = utf8.encode(name);
    const local = zipHeader(0x04034b50, 30);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0x0808, 6);
    local.writeUInt16LE(0, 8);
    local.writeUInt16LE(filename.length, 26);
    await write(stream, local);
    await write(stream, Buffer.from(filename));

    let crc = 0xffffffff;
    let size = 0;
    for await (const chunk of file.createReadStream()) {
        const data = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
        size += data.length;
        if (size > 0xffffffff) throw new Error("An audio file exceeds the ZIP format limit");
        crc = crcUpdate(crc, data);
        await write(stream, data);
    }
    crc = (crc ^ 0xffffffff) >>> 0;

    const descriptor = zipHeader(0x08074b50, 16);
    descriptor.writeUInt32LE(crc, 4);
    descriptor.writeUInt32LE(size, 8);
    descriptor.writeUInt32LE(size, 12);
    await write(stream, descriptor);
    return { name, crc, size, offset };
}

async function createZip(stream: WriteStream, entries: ArchiveEntry[]): Promise<void> {
    let offset = entries.reduce((total, entry) => total + 30 + utf8.encode(entry.name).length + entry.size + 16, 0);
    const centralStart = offset;
    for (const entry of entries) {
        const name = utf8.encode(entry.name);
        const header = zipHeader(0x02014b50, 46);
        header.writeUInt16LE(20, 4);
        header.writeUInt16LE(20, 6);
        header.writeUInt16LE(0x0808, 8);
        header.writeUInt16LE(0, 10);
        header.writeUInt32LE(entry.crc, 16);
        header.writeUInt32LE(entry.size, 20);
        header.writeUInt32LE(entry.size, 24);
        header.writeUInt16LE(name.length, 28);
        header.writeUInt32LE(entry.offset, 42);
        await write(stream, header);
        await write(stream, Buffer.from(name));
        offset += header.length + name.length;
    }
    const centralSize = offset - centralStart;
    const end = zipHeader(0x06054b50, 22);
    end.writeUInt16LE(entries.length, 8);
    end.writeUInt16LE(entries.length, 10);
    end.writeUInt32LE(centralSize, 12);
    end.writeUInt32LE(centralStart, 16);
    await write(stream, end);
}

async function writeZipFile(path: string, records: Array<{ locator: Locator; file: File }>): Promise<void> {
    const stream = createWriteStream(path);
    const entries: ArchiveEntry[] = [];
    let offset = 0;
    try {
        for (let index = 0; index < records.length; index++) {
            const name = safeName(records[index].locator.file_name, records[index].locator.job_id, index + 1);
            const entry = await appendEntry(stream, records[index].file, name, offset);
            entries.push(entry);
            offset += 30 + utf8.encode(name).length + entry.size + 16;
        }
        await createZip(stream, entries);
        await new Promise<void>((resolve, reject) => stream.end((error?: Error | null) => error ? reject(error) : resolve()));
    } catch (error) {
        stream.destroy();
        throw error;
    }
}

export async function GET(request: NextRequest) {
    const session = await getSession();
    if (!session) return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
    if (!canPlayAudio(session)) return NextResponse.json({ error: "Audio download is limited to Admin and Super Admin" }, { status: 403 });

    const startDate = request.nextUrl.searchParams.get("start_date");
    const endDate = request.nextUrl.searchParams.get("end_date");
    if (!validDate(startDate) || !validDate(endDate)) return NextResponse.json({ error: "Provide valid start_date and end_date values in YYYY-MM-DD format." }, { status: 400 });
    if (startDate > endDate) return NextResponse.json({ error: "Start date must be on or before end date." }, { status: 400 });
    if (startDate.slice(0, 7) !== endDate.slice(0, 7)) return NextResponse.json({ error: "The selected date range must be within one calendar month." }, { status: 400 });

    let directory: string | undefined;
    try {
        const jobs = await fetchJobs(request, startDate, endDate);
        if (!jobs.length) return NextResponse.json({ error: "No audio files were found for this date range." }, { status: 404 });

        const locators = await withConcurrency(jobs, 8, (job) => fetchLocator(request, job.job_id));
        const storage = new Storage();
        const records: Array<{ locator: Locator; file: File; size: number }> = [];
        for (const locator of locators) {
            if (!locator) continue;
            const match = GS_URI.exec(locator.gcs_uri.trim());
            if (!match) continue;
            const file = storage.bucket(match[1]).file(match[2]);
            const [exists] = await file.exists();
            if (!exists) continue;
            const [metadata] = await file.getMetadata();
            records.push({ locator, file, size: Number(metadata.size || 0) });
        }
        if (!records.length) return NextResponse.json({ error: "No available audio recordings were found for this date range." }, { status: 404 });
        const estimatedSize = records.reduce((sum, record) => sum + record.size, 0);
        if (!Number.isFinite(estimatedSize) || estimatedSize > MAX_ARCHIVE_BYTES) return NextResponse.json({ error: "The selected date range is too large for one ZIP (maximum 2 GB). Narrow the date range." }, { status: 413 });

        directory = await mkdtemp(join(tmpdir(), "pidilite-audio-"));
        const zipPath = join(directory, "audio-files.zip");
        await writeZipFile(zipPath, records);
        const nodeStream = createReadStream(zipPath);
        const cleanup = () => { if (directory) void rm(directory, { recursive: true, force: true }); };
        nodeStream.once("close", cleanup);
        nodeStream.once("error", cleanup);
        const stream = Readable.toWeb(nodeStream) as ReadableStream<Uint8Array>;
        return new Response(stream, { status: 200, headers: {
            "Content-Type": "application/zip",
            "Content-Disposition": `attachment; filename="audio-files_${startDate}_to_${endDate}.zip"`,
            "Cache-Control": "private, no-store",
            "X-Downloaded-Files": String(records.length),
            "X-Skipped-Files": String(jobs.length - records.length),
        } });
    } catch (error) {
        if (directory) await rm(directory, { recursive: true, force: true }).catch(() => undefined);
        const status = (error as { status?: number }).status || 502;
        return NextResponse.json({ error: error instanceof Error ? error.message : "Failed to prepare audio ZIP" }, { status });
    }
}
