import { ApiError } from "./api-client";
import type {
  InventoryApi,
  Movement,
  Page,
  ProductLabel,
  Stock,
} from "./inventory";
import { MAX_INTEGER } from "./inventory";

export const previewProducts: ProductLabel[] = [
  {
    productId: "11111111-1111-4111-8111-111111111111",
    name: "Bàn phím cơ Keychron K2",
    sku: "KEY-K2-001",
    category: "Bàn phím",
  },
  {
    productId: "22222222-2222-4222-8222-222222222222",
    name: "Chuột Logitech MX Master 3S",
    sku: "MOU-MX3-002",
    category: "Chuột",
  },
  {
    productId: "33333333-3333-4333-8333-333333333333",
    name: "Tai nghe Sony WH-1000XM5",
    sku: "AUD-XM5-003",
    category: "Âm thanh",
  },
  {
    productId: "44444444-4444-4444-8444-444444444444",
    name: "Màn hình Dell UltraSharp 27″",
    sku: "MON-U27-004",
    category: "Màn hình",
  },
  {
    productId: "55555555-5555-4555-8555-555555555555",
    name: "Hub USB-C Anker 7 trong 1",
    sku: "ACC-HUB-005",
    category: "Phụ kiện",
  },
  {
    productId: "66666666-6666-4666-8666-666666666666",
    name: "Giá đỡ laptop nhôm",
    sku: "ACC-STD-006",
    category: "Phụ kiện",
  },
  {
    productId: "77777777-7777-4777-8777-777777777777",
    name: "Đèn bàn làm việc",
    sku: "ACC-LMP-007",
    category: "Phụ kiện",
  },
  {
    productId: "88888888-8888-4888-8888-888888888888",
    name: "Lót bàn phím vải",
    sku: "ACC-MAT-008",
    category: "Phụ kiện",
  },
];

export function createPreviewInventory(): InventoryApi {
  const levels = [
    [48, 6, 10],
    [8, 5, 5],
    [0, 0, 5],
    [16, 2, 5],
    [32, 4, 8],
    [5, 1, 5],
  ];
  const stocks: Stock[] = levels.map(
    ([onHandQuantity, reservedQuantity, lowStockThreshold], i) => ({
      productId: previewProducts[i].productId,
      onHandQuantity,
      reservedQuantity,
      availableQuantity: onHandQuantity - reservedQuantity,
      lowStockThreshold,
      version: 1,
    }),
  );
  const movements: Movement[] = stocks.map((stock, i) => ({
    id: `receipt-${i}`,
    operationId: `preview-receipt-${i}`,
    productId: stock.productId,
    movementType: "RECEIPT",
    onHandDelta: stock.onHandQuantity,
    reservedDelta: 0,
    onHandAfter: stock.onHandQuantity,
    reservedAfter: 0,
    reason: "Nhập hàng đầu kỳ — dữ liệu minh họa",
    createdAt: "2026-11-22T02:00:00Z",
  }));
  stocks.forEach((stock, i) => {
    if (stock.reservedQuantity)
      movements.unshift({
        id: `reserve-${i}`,
        operationId: `preview-reserve-${i}`,
        productId: stock.productId,
        movementType: "RESERVE",
        onHandDelta: 0,
        reservedDelta: stock.reservedQuantity,
        onHandAfter: stock.onHandQuantity,
        reservedAfter: stock.reservedQuantity,
        reason: "Giữ hàng cho đơn minh họa",
        createdAt: "2026-11-22T03:00:00Z",
      });
  });
  const operations = new Map<
    string,
    { fingerprint: string; stock?: Stock; error?: ApiError }
  >();
  const fail = (code: string, message = code) =>
    new ApiError(message, code, code === "NOT_FOUND" ? 404 : 409);
  function page<T>(items: T[], number: number, pageSize: number): Page<T> {
    return structuredClone({
      items: items.slice((number - 1) * pageSize, number * pageSize),
      page: number,
      pageSize,
      total: items.length,
    });
  }
  function mutate(key: string, body: object, action: () => Stock): Stock {
    const fingerprint = JSON.stringify(body);
    const existing = operations.get(key);
    if (existing) {
      if (existing.fingerprint !== fingerprint)
        throw fail("IDEMPOTENCY_CONFLICT");
      if (existing.error) throw existing.error;
      return structuredClone(existing.stock!);
    }
    try {
      const stock = structuredClone(action());
      operations.set(key, { fingerprint, stock });
      return structuredClone(stock);
    } catch (error) {
      if (error instanceof ApiError)
        operations.set(key, { fingerprint, error });
      throw error;
    }
  }
  return {
    async list(query) {
      const items = stocks.filter(
        (s) =>
          query.lowStock === undefined ||
          s.availableQuantity <= s.lowStockThreshold === query.lowStock,
      );
      return page(items, query.page, query.pageSize);
    },
    async movements(productId, number) {
      return page(
        movements.filter((m) => m.productId === productId),
        number,
        10,
      );
    },
    async initialize(body, key) {
      return mutate(key, body, () => {
        if (!previewProducts.some((p) => p.productId === body.productId))
          throw fail("NOT_FOUND");
        const current = stocks.find((s) => s.productId === body.productId);
        if (current) {
          if (current.lowStockThreshold !== body.lowStockThreshold)
            throw fail("STOCK_CONFIGURATION_CONFLICT");
          return current;
        }
        const item = {
          ...body,
          onHandQuantity: 0,
          reservedQuantity: 0,
          availableQuantity: 0,
          version: 0,
        };
        stocks.unshift(item);
        return item;
      });
    },
    async adjust(body, key) {
      return mutate(key, body, () => {
        const current = stocks.find((s) => s.productId === body.productId);
        if (!current) throw fail("NOT_FOUND");
        if (current.version !== body.expectedVersion)
          throw fail("STOCK_VERSION_CONFLICT");
        if (current.onHandQuantity + body.delta < current.reservedQuantity)
          throw fail("INSUFFICIENT_STOCK");
        if (current.onHandQuantity + body.delta > MAX_INTEGER)
          throw fail("STOCK_LIMIT_EXCEEDED");
        current.onHandQuantity += body.delta;
        current.availableQuantity =
          current.onHandQuantity - current.reservedQuantity;
        current.version += 1;
        movements.unshift({
          id: crypto.randomUUID(),
          operationId: key,
          productId: body.productId,
          movementType: body.delta > 0 ? "RECEIPT" : "ADJUSTMENT",
          onHandDelta: body.delta,
          reservedDelta: 0,
          onHandAfter: current.onHandQuantity,
          reservedAfter: current.reservedQuantity,
          reason: body.reason,
          createdAt: new Date().toISOString(),
        });
        return current;
      });
    },
  };
}
