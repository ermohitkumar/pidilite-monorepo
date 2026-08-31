"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  LuChevronLeft,
  LuChevronRight,
  LuLogOut,
  LuPackage,
  LuSquareActivity,
  LuTable,
  LuUsers,
} from "react-icons/lu";
import { MdOutlineAudioFile } from "react-icons/md";

import { useAppStore } from "@/lib/store/useAppStore";
import { hasAccess, ResourceType } from "@/lib/auth/permissions";

type SidebarItem = {
  title: string;
  href: string;
  icon: any;
  resource?: ResourceType;
  requiredRole?: string;
};

const sidebarSections: { title: string; items: SidebarItem[] }[] = [
  {
    title: "sidebar",
    items: [
      {
        title: "Reports",
        href: "/reports",
        icon: LuTable,
        resource: "reports",
      },
      {
        title: "Monitor",
        href: "/monitor",
        icon: LuSquareActivity,
        resource: "monitor",
      },
      {
        title: "Files",
        href: "/files",
        icon: MdOutlineAudioFile,
        resource: "all_files",
      },
      {
        title: "Catalog",
        href: "/catalog",
        icon: LuPackage,
        resource: "library",
      },
      {
        title: "Users",
        href: "/users",
        icon: LuUsers,
        requiredRole: "super_admin",
      },
    ],
  },
];

export default function SideBar() {
  const pathname = usePathname();
  const [isExpanded, setIsExpanded] = useState(true);
  const user = useAppStore((state) => state.user);
  const userName = user?.full_name || user?.username || user?.email;
  const userRole =
    user?.role === "super_admin"
      ? "Super Admin"
      : user?.role === "admin"
        ? "Admin"
        : "User";

  // Don't render the sidebar on auth pages
  if (
    pathname === "/login" ||
    pathname.startsWith("/login/") ||
    pathname === "/forgot-password" ||
    pathname.startsWith("/forgot-password/") ||
    pathname === "/reset-password" ||
    pathname.startsWith("/reset-password/")
  ) {
    return null;
  }

  return (
    <aside
      className={`sticky top-0 flex h-screen flex-col bg-brand-fg border-r border-border transition-all duration-300 z-50 ${
        isExpanded ? "w-52" : "w-20"
      }`}
    >
      <div
        className={`relative flex items-center border-b border-border p-5 h-[72px] shrink-0 ${isExpanded ? "justify-between" : "justify-center"}`}
      >
        <div className="flex items-center gap-2 overflow-hidden mx-auto">
          <img
            src="/pidilite-seeklogo.png"
            alt="Pidilite Logo"
            className={isExpanded ? "h-12 w-25" : "h-8 w-12"}
          />
        </div>

        {/* Toggle Button */}
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="absolute -right-3 top-1/2 -translate-y-1/2 z-10 flex h-6 w-6 items-center justify-center rounded-full border border-border bg-surface text-text-subtle shadow-sm hover:bg-surface-raised hover:text-text"
        >
          {isExpanded ? (
            <LuChevronLeft className="h-4 w-4" />
          ) : (
            <LuChevronRight className="h-4 w-4" />
          )}
        </button>
      </div>

      <nav className="flex-1 space-y-6 overflow-y-auto p-5 scrollbar-hide">
        {sidebarSections.map((section) => (
          <div key={section.title}>
            <ul className="space-y-1">
              {section.items
                .filter((item) => {
                  if (
                    item.requiredRole === "super_admin" &&
                    user?.role !== "super_admin"
                  )
                    return false;
                  if (
                    process.env.NODE_ENV !== "production" &&
                    item.resource === "reports"
                  ) {
                    return true;
                  }
                  if (item.resource && !hasAccess(user, item.resource))
                    return false;
                  return true;
                })
                .map((item) => {
                  const isActive =
                    pathname === item.href ||
                    pathname.startsWith(`${item.href}/`) ||
                    (pathname === "/" && item.href === "/reports");
                  const Icon = item.icon;
                  return (
                    <li key={item.title}>
                      <Link
                        href={item.href}
                        className={`flex w-full items-center gap-3 rounded-md py-2 text-left text-sm transition-colors ${
                          isActive
                            ? "bg-brand-subtle font-medium text-brand"
                            : "text-text-subtle hover:bg-surface-raised hover:text-text"
                        } ${isExpanded ? "px-3" : "justify-center px-0"}`}
                        title={!isExpanded ? item.title : undefined}
                      >
                        <Icon
                          className={`h-5 w-5 shrink-0 ${isActive ? "text-brand" : "text-text-disabled"}`}
                        />
                        {isExpanded && (
                          <span className="whitespace-nowrap text-body-lg">
                            {item.title}
                          </span>
                        )}
                      </Link>
                    </li>
                  );
                })}
            </ul>
          </div>
        ))}
      </nav>

      <div
        className={`mt-auto mb-0 border-t border-border p-4 transition-all ${isExpanded ? "" : "flex flex-col items-center p-3"}`}
      >
        <div
          className={`flex items-center gap-2 py-3 ${isExpanded ? "" : "justify-center"}`}
        >
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand text-brand-fg text-sm font-medium shadow-sm uppercase">
            {user?.full_name?.[0] || "U"}
          </div>
          {isExpanded && (
            <div className="flex flex-col overflow-hidden">
              <p className="text-sm font-semibold truncate text-text">
                {userName}
              </p>
              <p className="text-xs text-text-subtle truncate">{userRole}</p>
            </div>
          )}
        </div>
        <form
          action="/api/logout"
          method="post"
          className={isExpanded ? "w-full" : "w-full flex justify-center"}
        >
          <button
            type="submit"
            className={`border border-border bg-surface text-xs font-medium text-text-subtle hover:bg-surface-raised hover:text-text flex justify-center items-center transition-colors ${
              isExpanded
                ? "w-full rounded-md px-3 py-1.5"
                : "w-8 h-8 rounded-full"
            }`}
            title="Sign out"
          >
            {isExpanded ? "Sign out" : <LuLogOut className="h-3 w-3" />}
          </button>
        </form>
      </div>
    </aside>
  );
}
