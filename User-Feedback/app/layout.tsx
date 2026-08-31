import { AuthProvider } from "@/components/providers/AuthProvider";
import { QueryProvider } from "@/components/providers/QueryProvider";
import { RouteGuard } from "@/components/providers/RouteGuard";
import SideBar from "@/components/SideBar";
import { getSession } from "@/lib/auth/session";
import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { Toaster } from "sonner";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Pidilite User Feedback App",
  description: "Pidilite User Feedback App",
  icons: {
    icon: "/pidilite-seeklogo.png",
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
      className={`${inter.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <body className="min-h-full flex flex-col font-sans" suppressHydrationWarning>
        <QueryProvider>
          <AuthProvider initialUser={session}>
            <RouteGuard>
              <div className="flex h-screen w-full bg-zinc-50 overflow-hidden">
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
