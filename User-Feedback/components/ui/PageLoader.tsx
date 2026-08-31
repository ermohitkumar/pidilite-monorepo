import { LuLoader } from "react-icons/lu";

export function PageLoader({ text = "Loading...", fullScreen = false }: { text?: string; fullScreen?: boolean }) {
    return (
        <div className={`flex flex-col items-center justify-center gap-4 ${fullScreen ? "h-screen w-full bg-bg" : "h-full min-h-[50vh] w-full"}`}>
            <LuLoader className="h-8 w-8 animate-spin text-brand" />
            <div className="text-body-md text-text-subtle font-medium">{text}</div>
        </div>
    );
}
