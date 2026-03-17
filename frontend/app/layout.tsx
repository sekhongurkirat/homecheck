import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HomeCheck — Know What's Around Your Next Home",
  description:
    "Instantly check a home address for nearby highways, industrial facilities, flood zones, rail lines, and more.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
