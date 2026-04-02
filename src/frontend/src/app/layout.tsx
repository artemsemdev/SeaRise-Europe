import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "SeaRise Europe",
  description:
    "Coastal sea-level exposure explorer for Europe under IPCC AR6 scenarios.",
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
