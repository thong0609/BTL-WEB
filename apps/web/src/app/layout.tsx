import type { Metadata } from "next";
import { OrderSessionProvider } from "@/components/order-session";
import "./globals.css";

export const metadata: Metadata = {
  title: "Commerce | Đơn hàng",
  description: "Đặt hàng và theo dõi đơn hàng của cửa hàng.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="vi"><body><OrderSessionProvider>{children}</OrderSessionProvider></body></html>;
}
