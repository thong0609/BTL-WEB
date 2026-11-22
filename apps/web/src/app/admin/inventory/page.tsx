import type { Metadata } from "next";
import { InventoryDashboard } from "@/components/inventory/dashboard";
import "./inventory.css";

export const metadata: Metadata = {
  title: "Quản lý tồn kho | Commerce",
  description: "Quản trị tồn kho, nhập hàng và lịch sử biến động.",
};

export default async function InventoryPage({
  searchParams,
}: {
  searchParams: Promise<{ preview?: string }>;
}) {
  const params = await searchParams;
  return <InventoryDashboard initialPreview={params.preview === "1"} />;
}
