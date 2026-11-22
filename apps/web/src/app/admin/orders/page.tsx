import { OrderList } from "@/components/order-list";

export default function AdminOrdersPage() {
  return <main className="order-main"><h1 className="order-title">Quản lý đơn hàng</h1><OrderList admin /></main>;
}
