import FileInsightClient from './file-insight-client';

export default async function InsightsFilePage({ params }: { params: Promise<{ id: string }> }) {
    const { id } = await params;
    return (
        <div className="h-full min-h-0">
            <FileInsightClient fileId={id} />
        </div>
    );
}
