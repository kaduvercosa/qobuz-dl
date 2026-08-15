import type { Metadata } from "next";
import { Inter, Space_Mono } from "next/font/google";
import "./globals.css";
import { ThemeProvider } from "@/components/theme-provider";
import { StatusBarProvider } from "@/lib/status-bar/context";
import { StatusBar } from "@/components/status-bar/status-bar";
import { Toaster } from "@/components/ui/toaster";

const inter = Inter({ subsets: ["latin"], variable: "--font-sans" });
const spaceMono = Space_Mono({ weight: ["400", "700"], subsets: ["latin"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "Qobuz-DL // Ultimate Lossless Downloader",
  description: "High-Res Lossless Audio Downloader & Explorer powered by Next.js & Python FastAPI",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="pt-BR" suppressHydrationWarning>
      <body className={`${inter.variable} ${spaceMono.variable} font-sans antialiased min-h-screen bg-background text-foreground`}>
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem disableTransitionOnChange>
          <StatusBarProvider>
            {children}
            <StatusBar />
            <Toaster />
          </StatusBarProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
