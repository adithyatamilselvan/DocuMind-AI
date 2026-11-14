import { FileOutput, History, FileText, FlaskConical, Library, LayoutDashboard, MessagesSquare, Search, Sparkles, type LucideIcon, Settings, Upload, Users } from "lucide-react";

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
      { href: "/search", label: "Search", icon: Search },
      { href: "/knowledge-bases", label: "Knowledge bases", icon: Library },
      { href: "/analysis", label: "Research", icon: FlaskConical },
      { href: "/reports", label: "Reports", icon: FileOutput },
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
      { href: "/activity", label: "Activity", icon: History },
      { href: "/settings", label: "Settings", icon: Settings },
    ],
  },
];
