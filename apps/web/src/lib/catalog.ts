/**
 * Types, validation utilities, and API client functions for the Catalog module.
 * Strictly aligned with docs/contracts/openapi.yaml.
 */

import { apiRequest } from "./api-client";

export interface Category {
  id: string;
  name: string;
  slug: string;
  description: string | null;
  isVisible: boolean;
}

export interface ProductImageItem {
  id: string;
  url: string;
  altText: string | null;
  sortOrder: number;
}

export type ProductStatus = "DRAFT" | "ACTIVE" | "DISCONTINUED";
export type Availability = "IN_STOCK" | "OUT_OF_STOCK" | "UNKNOWN";
export type SortOption = "NEWEST" | "PRICE_ASC" | "PRICE_DESC";

export interface Product {
  id: string;
  sku: string;
  slug: string;
  name: string;
  categoryId: string;
  description: string;
  specifications: Record<string, string>;
  priceAmount: string;
  currency: "VND";
  status: ProductStatus;
  version: number;
  images: ProductImageItem[];
  availability: Availability;
}

export interface PageResponse<T> {
  items: T[];
  page: number;
  pageSize: number;
  total: number;
}

export interface CategoryInput {
  name: string;
  slug: string;
  description?: string;
  isVisible?: boolean;
}

export interface CategoryPatch {
  name?: string;
  slug?: string;
  description?: string;
  isVisible?: boolean;
}

export interface ProductInput {
  sku: string;
  slug: string;
  name: string;
  categoryId: string;
  description: string;
  specifications?: Record<string, string>;
  priceAmount: string;
  currency?: "VND";
  status?: ProductStatus;
}

export interface ProductPatch {
  expectedVersion: number;
  slug?: string;
  name?: string;
  categoryId?: string;
  description?: string;
  specifications?: Record<string, string>;
  priceAmount?: string;
  currency?: "VND";
  status?: ProductStatus;
  imageIds?: string[];
}

export interface ProductQuery {
  page?: number;
  pageSize?: number;
  q?: string;
  categoryId?: string;
  minPrice?: string;
  maxPrice?: string;
  sort?: SortOption;
  status?: ProductStatus;
}

const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
const DIGITS_PATTERN = /^[0-9]+$/;

export function generateSlug(input: string): string {
  return input
    .toLowerCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[đĐ]/g, "d")
    .replace(/[^a-z0-9\s-]/g, "")
    .trim()
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-");
}

export function isValidSlug(slug: string): boolean {
  return slug.length >= 1 && slug.length <= 180 && SLUG_PATTERN.test(slug);
}

export function isValidPriceString(price: string): boolean {
  return DIGITS_PATTERN.test(price.trim());
}

export function formatVND(amount: string | number): string {
  const num = typeof amount === "string" ? Number.parseInt(amount, 10) : amount;
  if (!Number.isFinite(num)) return "0 ₫";
  return new Intl.NumberFormat("vi-VN", { style: "currency", currency: "VND" }).format(num);
}

export function getSavedAdminToken(): string {
  if (typeof window === "undefined") return "";
  return window.localStorage.getItem("catalog_admin_token") || "";
}

function buildQueryString(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && String(value).trim() !== "") {
      q.set(key, String(value).trim());
    }
  }
  const qs = q.toString();
  return qs ? `?${qs}` : "";
}

function authHeaders(token?: string): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

// ──────────────────────────────────────────────
// Public Catalog API
// ──────────────────────────────────────────────

export async function fetchCategories(
  page = 1,
  pageSize = 50,
  signal?: AbortSignal
): Promise<PageResponse<Category>> {
  const qs = buildQueryString({ page, pageSize });
  return apiRequest<PageResponse<Category>>(`/categories${qs}`, { signal });
}

export async function fetchProducts(
  query: ProductQuery = {},
  signal?: AbortSignal
): Promise<PageResponse<Product>> {
  const qs = buildQueryString({
    page: query.page ?? 1,
    pageSize: query.pageSize ?? 20,
    q: query.q,
    categoryId: query.categoryId,
    minPrice: query.minPrice,
    maxPrice: query.maxPrice,
    sort: query.sort,
  });
  return apiRequest<PageResponse<Product>>(`/products${qs}`, { signal });
}

export async function fetchProductDetail(id: string, signal?: AbortSignal): Promise<Product> {
  return apiRequest<Product>(`/products/${id}`, { signal });
}

// ──────────────────────────────────────────────
// Admin Catalog API
// ──────────────────────────────────────────────

export async function fetchAdminCategories(
  token?: string,
  page = 1,
  pageSize = 50,
  signal?: AbortSignal
): Promise<PageResponse<Category>> {
  const qs = buildQueryString({ page, pageSize });
  return apiRequest<PageResponse<Category>>(`/admin/categories${qs}`, {
    headers: authHeaders(token),
    signal,
  });
}

export async function createAdminCategory(
  data: CategoryInput,
  token?: string
): Promise<Category> {
  return apiRequest<Category>("/admin/categories", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(token),
    },
    body: JSON.stringify(data),
  });
}

export async function patchAdminCategory(
  id: string,
  data: CategoryPatch,
  token?: string
): Promise<Category> {
  return apiRequest<Category>(`/admin/categories/${id}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(token),
    },
    body: JSON.stringify(data),
  });
}

export async function fetchAdminProducts(
  token?: string,
  query: ProductQuery = {},
  signal?: AbortSignal
): Promise<PageResponse<Product>> {
  const qs = buildQueryString({
    page: query.page ?? 1,
    pageSize: query.pageSize ?? 20,
    q: query.q,
    categoryId: query.categoryId,
    minPrice: query.minPrice,
    maxPrice: query.maxPrice,
    sort: query.sort,
    status: query.status,
  });
  return apiRequest<PageResponse<Product>>(`/admin/products${qs}`, {
    headers: authHeaders(token),
    signal,
  });
}

export async function fetchAdminProductDetail(
  id: string,
  token?: string,
  signal?: AbortSignal
): Promise<Product> {
  return apiRequest<Product>(`/admin/products/${id}`, {
    headers: authHeaders(token),
    signal,
  });
}

export async function createAdminProduct(
  data: ProductInput,
  token?: string
): Promise<Product> {
  return apiRequest<Product>("/admin/products", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(token),
    },
    body: JSON.stringify({
      currency: "VND",
      status: "DRAFT",
      ...data,
    }),
  });
}

export async function patchAdminProduct(
  id: string,
  data: ProductPatch,
  token?: string
): Promise<Product> {
  return apiRequest<Product>(`/admin/products/${id}`, {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      ...authHeaders(token),
    },
    body: JSON.stringify(data),
  });
}

export async function uploadProductImage(
  productId: string,
  file: File,
  altText?: string,
  token?: string
): Promise<ProductImageItem> {
  const formData = new FormData();
  formData.append("file", file);
  if (altText && altText.trim()) {
    formData.append("altText", altText.trim());
  }
  return apiRequest<ProductImageItem>(`/admin/products/${productId}/images`, {
    method: "POST",
    headers: authHeaders(token),
    body: formData,
  });
}

export async function deleteProductImage(
  productId: string,
  imageId: string,
  token?: string
): Promise<void> {
  return apiRequest<void>(`/admin/products/${productId}/images/${imageId}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
}
