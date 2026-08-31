import { getBackendApiUrl } from "@/lib/auth/env";
import { SESSION_COOKIE, getSession } from "@/lib/auth/session";
import { NextRequest, NextResponse } from "next/server";
import { Readable } from "node:stream";
import { Storage } from "@google-cloud/storage";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 60;

const GS_URI = /^gs:\/\/([a-z0-9][a-z0-9._-]{1,61}[a-z0-9])\/(.+)$/;

type Locator = {
    job_id: string;
    file_name: string;
    gcs_uri: string;
    content_type: string;
};

function parseGcsUri(uri: string): { bucket: string; object: string } | null {
    const match = GS_URI.exec(uri.trim());
    if (!match) return null;
    return { bucket: match[1], object: match[2] };
}

function parseRange(header: string | null, size: number): { start: number; end: number } | null {
    if (!header) return null;
    const match = /^bytes=(\d*)-(\d*)$/.exec(header.trim());
    if (!match) return null;
    const start = match[1] ? Number(match[1]) : 0;
    const end = match[2] ? Number(match[2]) : size - 1;
    if (!Number.isFinite(start) || !Number.isFinite(end) || start > end || start >= size) {
        return null;
    }
    return { start, end: Math.min(end, size - 1) };
}

function nodeReadableToWeb(stream: Readable): ReadableStream<Uint8Array> {
    return new ReadableStream({
        start(controller) {
            stream.on("data", (chunk: Buffer | string) => {
                const buffer = typeof chunk === "string" ? Buffer.from(chunk) : chunk;
                controller.enqueue(new Uint8Array(buffer));
            });
            stream.on("end", () => {
                try {
                    controller.close();
                } catch {
                    /* already closed */
                }
            });
            stream.on("error", (error) => {
                try {
                    controller.error(error);
                } catch {
                    /* already closed */
                }
            });
        },
        cancel() {
            stream.destroy();
        },
    });
}

async function fetchLocator(jobId: string, request: NextRequest): Promise<Locator> {
    const backend = getBackendApiUrl();
    const token = request.cookies.get(SESSION_COOKIE)?.value;
    const headers: HeadersInit = { Accept: "application/json" };
    if (token) {
        headers.Authorization = `Bearer ${token}`;
        headers.Cookie = `${SESSION_COOKIE}=${token}`;
    }
    const res = await fetch(
        `${backend}/api/v1/reports/audio-locator?job_id=${encodeURIComponent(jobId)}`,
        { headers, cache: "no-store" },
    );
    const json = (await res.json().catch(() => null)) as
        | { success?: boolean; data?: Locator; message?: string }
        | null;
    if (!res.ok || !json?.success || !json.data?.gcs_uri) {
        const error = new Error(
            json?.message || (json as { detail?: string } | null)?.detail || "Audio not found",
        ) as Error & { status?: number };
        if (res.status === 401 || res.status === 403 || res.status === 404) {
            error.status = res.status;
        } else if (res.status >= 500) {
            error.status = 502;
        } else {
            error.status = 404;
        }
        throw error;
    }
    return json.data;
}

async function audioResponse(
    request: NextRequest,
    jobId: string,
    body: boolean,
): Promise<Response> {
    if (process.env.NODE_ENV === "production") {
        const session = await getSession();
        if (!session) {
            return NextResponse.json({ error: "Not authenticated" }, { status: 401 });
        }
    }

    if (!jobId || jobId.length < 8 || jobId.length > 64) {
        return NextResponse.json({ error: "Invalid job" }, { status: 400 });
    }

    try {
        const locator = await fetchLocator(jobId, request);
        const parsed = parseGcsUri(locator.gcs_uri);
        if (!parsed) {
            return NextResponse.json({ error: "Audio path is invalid" }, { status: 400 });
        }

        const storage = new Storage();
        const file = storage.bucket(parsed.bucket).file(parsed.object);
        const [exists] = await file.exists();
        if (!exists) {
            return NextResponse.json({ error: "Audio file is missing" }, { status: 404 });
        }

        const [metadata] = await file.getMetadata();
        const size = Number(metadata.size || 0);
        const contentType =
            locator.content_type && locator.content_type !== "application/octet-stream"
                ? locator.content_type
                : metadata.contentType || locator.content_type || "audio/mpeg";
        const range = body ? parseRange(request.headers.get("range"), size) : null;

        const headers = new Headers({
            "Content-Type": contentType,
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, no-store",
            "Content-Disposition": `inline; filename="${(locator.file_name || "recording").replaceAll('"', "")}"`,
        });

        if (!body) {
            if (size > 0) headers.set("Content-Length", String(size));
            return new Response(null, { status: 200, headers });
        }

        if (range) {
            const stream = file.createReadStream({ start: range.start, end: range.end });
            headers.set("Content-Range", `bytes ${range.start}-${range.end}/${size}`);
            headers.set("Content-Length", String(range.end - range.start + 1));
            return new Response(nodeReadableToWeb(stream), {
                status: 206,
                headers,
            });
        }

        const stream = file.createReadStream();
        if (size > 0) headers.set("Content-Length", String(size));
        return new Response(nodeReadableToWeb(stream), {
            status: 200,
            headers,
        });
    } catch (error) {
        const status = (error as { status?: number }).status || 502;
        const message = error instanceof Error ? error.message : "Failed to load audio";
        return NextResponse.json({ error: message }, { status });
    }
}

export async function GET(
    request: NextRequest,
    context: { params: Promise<{ jobId: string }> },
) {
    const { jobId } = await context.params;
    return audioResponse(request, jobId, true);
}

export async function HEAD(
    request: NextRequest,
    context: { params: Promise<{ jobId: string }> },
) {
    const { jobId } = await context.params;
    return audioResponse(request, jobId, false);
}
