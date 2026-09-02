import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL("https://talli.no"),
  title: {
    default: "Talli – regnskap og årsoppgjør for holdingselskap",
    template: "%s – Talli",
  },
  description:
    "Sjekk gratis om Talli passer for holdingselskapet før konto eller betaling.",
  keywords: [
    "regnskap for holdingselskap",
    "årsoppgjør holdingselskap",
    "aksjonærregisteroppgaven",
    "skattemelding for selskap",
    "årsregnskap",
  ],
  applicationName: "Talli",
  referrer: "no-referrer",
  authors: [{ name: "ELMER WELFIS", url: "https://talli.no" }],
  creator: "ELMER WELFIS",
  publisher: "ELMER WELFIS",
  formatDetection: { email: false, address: false, telephone: false },
  openGraph: {
    type: "website",
    locale: "nb_NO",
    url: "https://talli.no",
    siteName: "Talli",
    title: "Talli – hele selskapsåret i ett rolig løp",
    description: "Sjekk gratis om Talli passer for holdingselskapet før konto eller betaling.",
    images: [{ url: "/og.png", width: 1729, height: 910, alt: "Talli – hele selskapsåret i ett rolig løp" }],
  },
  twitter: {
    card: "summary_large_image",
    title: "Talli – hele selskapsåret i ett rolig løp",
    description: "Sjekk gratis om Talli passer for holdingselskapet før konto eller betaling.",
    images: ["/og.png"],
  },
  icons: {
    icon: "/icon.svg",
    apple: "/apple-icon.png",
  },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0d6b57",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="no" data-scroll-behavior="smooth">
      <body>{children}</body>
    </html>
  );
}
