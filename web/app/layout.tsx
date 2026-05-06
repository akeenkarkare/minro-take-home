import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "minro enrichment",
  description: "People enrichment platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
