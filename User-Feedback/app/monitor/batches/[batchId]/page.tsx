import BatchDetailClient from './batch-detail-client';

export default async function BatchDetailPage({ params }: { params: Promise<{ batchId: string }> }) {
    const { batchId } = await params;
    return <BatchDetailClient batchId={batchId} />;
}
