import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Talli",
  description: "Holding-first filing assistant for Norwegian holding companies.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="no">
      <body>{children}</body>
    </html>
  );
}
