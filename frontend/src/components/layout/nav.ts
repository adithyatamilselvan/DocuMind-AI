import { FileText, LayoutDashboard, MessagesSquare, Sparkles, type LucideIcon, Settings, Upload, Users } from "lucide-react";

export type NavItem = { href: string; label: string; icon: LucideIcon };
export type NavGroup = { label: string; items: NavItem[] };

/** Only routes that exist are listed. New feature phases append their entries here. */
export const NAV_GROUPS: NavGroup[] = [
  {
    label: "Overview",
    items: [{ href: "/dashboard", label: "Dashboard", icon: LayoutDashboard }],
  },
  {
    label: "Workspace AI",
    items: [
      { href: "/assistant", label: "Assistant", icon: MessagesSquare },
      { href: "/insights", label: "Insights", icon: Sparkles },
    ],
  },
  {
    label: "Library",
    items: [
      { href: "/documents", label: "Documents", icon: FileText },
      { href: "/upload", label: "Upload", icon: Upload },
    ],
  },
  {
    label: "Administration",
    items: [
      { href: "/workspace", label: "Workspace", icon: Users },
      { href: "/settings", label: "Settings", icon: Settings },
    ],
  },
];
