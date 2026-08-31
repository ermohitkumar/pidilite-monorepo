import { LuLoader, LuFileWarning } from 'react-icons/lu';

export function TableLoading({ colSpan }: { colSpan: number }) {
    return (
        <tr>
            <td colSpan={colSpan} className="px-5 py-24 text-center">
                <div className="flex flex-col items-center justify-center text-text-disabled">
                    <LuLoader className="h-8 w-8 animate-spin mb-4 text-brand" />
                    <p className="text-body-md">Loading data...</p>
                </div>
            </td>
        </tr>
    );
}

export function TableEmpty({ colSpan, message = "No records found." }: { colSpan: number; message?: string }) {
    return (
        <tr>
            <td colSpan={colSpan} className="px-5 py-24 text-center">
                <div className="flex flex-col items-center justify-center text-text-disabled">
                    <LuFileWarning className="h-8 w-8 mb-4 opacity-50" />
                    <p className="text-body-md">{message}</p>
                </div>
            </td>
        </tr>
    );
}
