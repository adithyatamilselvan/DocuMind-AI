import { LayoutDashboard, type LucideIcon, Settings, Users } from "lucide-react";

export type NavItem = { href: string; label: string; icon: LucideIcon };
export type NavGroup = { label: string; items: NavItem[] };

/** Only routes that exist are listed. New feature phases append their entries here. */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Overview",
    items: [{ href: "/dashboard", label: "Dashboard", icon: LayoutDashboard }],
  },
  {
    label: "Administration",
    items: [
      { href: "/workspace", label: "Workspace", icon: Users },
      { href: "/settings", label: "Settings", icon: Settings },
    ],
  },
];
