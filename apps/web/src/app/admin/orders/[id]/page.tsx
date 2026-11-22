import { OrderDetail } from "@/components/order-detail";

export default async function AdminOrderPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <main className="order-main"><h1 className="order-title">Xử lý đơn hàng</h1><OrderDetail id={id} admin /></main>;
}
