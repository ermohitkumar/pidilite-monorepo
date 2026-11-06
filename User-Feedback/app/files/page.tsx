import { Suspense } from 'react';

import FilesClient from './files-client';

export default function FilesPage() {
    return (
        <Suspense fallback={<div className="p-8 text-sm text-text-subtle">Loading files…</div>}>
            <FilesClient />
        </Suspense>
    );
}
