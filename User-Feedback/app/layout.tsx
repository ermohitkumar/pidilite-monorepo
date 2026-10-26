import { AuthProvider } from "@/components/providers/AuthProvider";
import { QueryProvider } from "@/components/providers/QueryProvider";
import { RouteGuard } from "@/components/providers/RouteGuard";
import SideBar from "@/components/SideBar";
import { getSession } from "@/lib/auth/session";
import type { Metadata } from "next";
import localFont from "next/font/local";
import { Toaster } from "sonner";
import "./globals.css";

const chillax = localFont({
  src: [
    { path: "./fonts/Chillax-Regular.woff2", weight: "400", style: "normal" },
    { path: "./fonts/Chillax-Medium.woff2", weight: "500", style: "normal" },
    { path: "./fonts/Chillax-Semibold.woff2", weight: "600", style: "normal" },
    { path: "./fonts/Chillax-Bold.woff2", weight: "700", style: "normal" },
  ],
  variable: "--font-chillax",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Samvad",
  description: "Samvad user feedback",
  icons: {
    icon: "/samvad-mark.png",
  },
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const session = await getSession();

  return (
    <html
      lang="en"
      className={`${chillax.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col font-sans" suppressHydrationWarning>
        <QueryProvider>
          <AuthProvider initialUser={session}>
            <RouteGuard>
              <div className="flex h-screen w-full bg-bg overflow-hidden">
                <SideBar />
                <div className="flex-1 overflow-y-auto">
                  {children}
                </div>
              </div>
            </RouteGuard>
          </AuthProvider>
        </QueryProvider>
        <Toaster position="top-right" richColors />
      </body>
    </html>
  );
}
