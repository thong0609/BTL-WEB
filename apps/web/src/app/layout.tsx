import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Commerce | Kiểm tra kết nối",
  description: "Kiểm tra kết nối frontend, gateway và Catalog service.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="vi"><body>{children}</body></html>;
}
