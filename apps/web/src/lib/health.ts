import { apiRequest, ApiError } from "./api-client";

export type CatalogHealth = {
  service: "catalog-service";
  status: "alive";
  checks: Record<string, string>;
};

export async function getCatalogHealth(signal?: AbortSignal): Promise<CatalogHealth> {
  const value = await apiRequest<unknown>("/health/catalog", { signal });
  if (
    typeof value !== "object" || value === null ||
    !("service" in value) || value.service !== "catalog-service" ||
    !("status" in value) || value.status !== "alive" ||
    !("checks" in value) || typeof value.checks !== "object" || value.checks === null ||
    Array.isArray(value.checks) || !Object.values(value.checks).every((item) => typeof item === "string")
  ) {
    throw new ApiError("Dữ liệu kiểm tra kết nối không hợp lệ.", "INVALID_RESPONSE", 200);
  }
  return value as CatalogHealth;
}
