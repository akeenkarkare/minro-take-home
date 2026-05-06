import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "minro enrichment",
  description: "People enrichment platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen font-sans antialiased">
        <header className="border-b border-border">
          <nav className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
            <Link href="/" className="text-base font-semibold tracking-tight">
              minro<span className="text-muted-foreground"> · enrichment</span>
            </Link>
            <ul className="flex items-center gap-6 text-sm text-muted-foreground">
              <li>
                <Link href="/" className="hover:text-foreground">
                  Upload
                </Link>
              </li>
              <li>
                <Link href="/people" className="hover:text-foreground">
                  People
                </Link>
              </li>
              <li>
                <Link href="/chat" className="hover:text-foreground">
                  Chat
                </Link>
              </li>
            </ul>
          </nav>
        </header>
        <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
