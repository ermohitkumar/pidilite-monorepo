import type { AppUser } from "@/lib/api/users";

export const AVAILABLE_RESOURCES = [
  { label: "Reports", value: "reports" },
  { label: "Monitor", value: "monitor" },
  { label: "All Files", value: "all_files" },
  { label: "File Insight", value: "file_insight" },
  { label: "Catalog", value: "library" },
] as const;

export type ResourceType = (typeof AVAILABLE_RESOURCES)[number]["value"];

/**
 * Helper function to check if a user has access to a specific resource.
 * Super Admins inherently have access to everything.
 */
export function hasAccess(
  user: Partial<AppUser> | null | undefined,
  resource: ResourceType,
): boolean {
  if (!user) return false;
  if (user.role === "super_admin") return true;

  // Fallback if allowed_resources isn't available
  if (!user.allowed_resources || !Array.isArray(user.allowed_resources)) {
    return false;
  }

  if (user.allowed_resources.includes(resource)) return true;
  const granted = user.allowed_resources as string[];
  // Legacy grants still used "dashboard" / "metrics" for the old mock pages.
  if (resource === "reports" && (granted.includes("dashboard") || granted.includes("metrics"))) {
    return true;
  }
  return false;
}

/**
 * Global map defining which routes require which permissions.
 * Keys are route prefixes (e.g., '/catalog' covers '/catalog/123').
 * If a route is not in this map, it is considered public or accessible to all authenticated users.
 */
export const ROUTE_PERMISSIONS: Record<string, ResourceType | "super_admin"> = {
  "/reports": "reports",
  "/monitor": "monitor",
  "/files": "all_files",
  "/catalog": "library",
  "/users": "super_admin",
};

/**
 * Finds the first route in ROUTE_PERMISSIONS that the user has access to.
 * Useful for fallback redirects when a user lands on a page they can't access.
 */
export function getFirstAccessibleRoute(
  user: Partial<AppUser> | null | undefined,
): string | null {
  if (!user) return null;
  if (user.role === "super_admin") return "/reports";

  for (const [route, permission] of Object.entries(ROUTE_PERMISSIONS)) {
    if (hasAccess(user, permission as any)) {
      return route;
    }
  }

  return null;
}
