"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  LuChevronLeft,
  LuChevronRight,
  LuClipboardCheck,
  LuFileText,
  LuHouse,
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
        title: "Home",
        href: "/",
        icon: LuHouse,
        resource: "reports",
      },
      {
        title: "Summary",
        href: "/reports",
        icon: LuFileText,
        resource: "reports",
      },
      {
        title: "Feedback",
        href: "/reports/insights",
        icon: LuTable,
        resource: "reports",
      },
      {
        title: "Compliance",
        href: "/reports/compliance",
        icon: LuClipboardCheck,
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
        title: "Library",
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
      className={`sticky top-0 flex h-screen flex-col bg-sidebar text-white transition-all duration-300 z-50 ${
        isExpanded ? "w-56" : "w-20"
      }`}
    >
      <div
        className={`relative flex items-center border-b border-white/10 px-4 h-[76px] shrink-0 ${isExpanded ? "justify-between" : "justify-center"}`}
      >
        <div className="flex items-center overflow-hidden">
          <img
            src={isExpanded ? "/samvad-logo-on-dark.png" : "/samvad-mark.png"}
            alt="Samvad"
            className={isExpanded ? "h-8 w-auto" : "h-8 w-8 object-contain"}
          />
        </div>

        {/* Toggle Button */}
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="absolute -right-3 top-1/2 -translate-y-1/2 z-10 flex h-6 w-6 items-center justify-center rounded-full border border-white/15 bg-sidebar text-white/80 shadow-sm hover:bg-sidebar-active hover:text-white"
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
                    item.href === "/"
                      ? pathname === "/"
                      : item.href === "/reports"
                        ? pathname === "/reports" || pathname === "/reports/summaries"
                        : pathname === item.href || pathname.startsWith(`${item.href}/`);
                  const Icon = item.icon;
                  return (
                    <li key={item.title}>
                      <Link
                        href={item.href}
                        className={`flex w-full items-center gap-3 rounded-lg py-2 text-left text-sm transition-colors ${
                          isActive
                            ? "bg-sidebar-active font-medium text-white"
                            : "text-[#c4c0cc] hover:bg-white/5 hover:text-white"
                        } ${isExpanded ? "px-3" : "justify-center px-0"}`}
                        title={!isExpanded ? item.title : undefined}
                      >
                        <Icon
                          className={`h-5 w-5 shrink-0 ${isActive ? "text-white" : "text-[#a09ea4]"}`}
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
        className={`mt-auto mb-0 border-t border-white/10 p-4 transition-all ${isExpanded ? "" : "flex flex-col items-center p-3"}`}
      >
        <div
          className={`flex items-center gap-2 py-3 ${isExpanded ? "" : "justify-center"}`}
        >
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-brand text-white text-sm font-medium shadow-sm uppercase">
            {user?.full_name?.[0] || "U"}
          </div>
          {isExpanded && (
            <div className="flex flex-col overflow-hidden">
              <p className="text-sm font-semibold truncate text-white">
                {userName}
              </p>
              <p className="text-xs text-white/60 truncate">{userRole}</p>
            </div>
          )}
        </div>
        <form
          action="/bff/logout"
          method="post"
          className={isExpanded ? "w-full" : "w-full flex justify-center"}
        >
          <button
            type="submit"
            className={`border border-white/20 bg-white/5 text-xs font-medium text-white/80 hover:bg-white/10 hover:text-white flex justify-center items-center transition-colors ${
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
