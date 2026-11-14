"use client";

import { MessageSquarePlus, MoreHorizontal, Pencil, Search, Trash2 } from "lucide-react";
import { useState } from "react";

import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog"; // fmt: skip
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"; // fmt: skip
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import type { Conversation } from "@/types";

export function ConversationSidebar({
  items, loading, activeId, search, onSearch, onSelect, onNew, onRename, onDelete,
}: {
  items: Conversation[];
  loading: boolean;
  activeId: string | null;
  search: string;
  onSearch: (v: string) => void;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
}) {
  const [renaming, setRenaming] = useState<Conversation | null>(null);
  const [title, setTitle] = useState("");
  const [deleting, setDeleting] = useState<Conversation | null>(null);

  return (
    <div className="flex h-full flex-col gap-3 p-3">
      <Button onClick={onNew} className="w-full justify-start gap-2">
        <MessageSquarePlus className="size-4" aria-hidden /> New chat
      </Button>
      <div className="relative">
        <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
        <Input aria-label="Search conversations" placeholder="Search chats" className="h-9 pl-8" value={search} onChange={(e) => onSearch(e.target.value)} />
      </div>
      <nav aria-label="Conversations" className="-mx-1 flex-1 space-y-0.5 overflow-y-auto px-1">
        {loading ? (
          Array.from({ length: 5 }, (_, i) => <Skeleton key={i} className="h-9" />)
        ) : items.length === 0 ? (
          <p className="px-2 py-6 text-center text-sm text-muted-foreground">{search ? "No chats match." : "No conversations yet."}</p>
        ) : (
          items.map((c) => (
            <div key={c.id} className={cn("group flex items-center rounded-md hover:bg-muted", c.id === activeId && "bg-accent")}>
              <button
                type="button"
                onClick={() => onSelect(c.id)}
                aria-current={c.id === activeId ? "page" : undefined}
                className="min-w-0 flex-1 truncate rounded-md px-2.5 py-2 text-left text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
              >
                {c.title}
              </button>
              <DropdownMenu>
                <DropdownMenuTrigger render={<Button variant="ghost" size="icon-xs" aria-label={`Actions for ${c.title}`} className="mr-1 opacity-60 group-hover:opacity-100" />}>
                  <MoreHorizontal className="size-3.5" />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="end">
                  <DropdownMenuItem onClick={() => { setRenaming(c); setTitle(c.title); }}>
                    <Pencil className="size-4" aria-hidden /> Rename
                  </DropdownMenuItem>
                  <DropdownMenuItem onClick={() => setDeleting(c)}>
                    <Trash2 className="size-4" aria-hidden /> Delete
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>
            </div>
          ))
        )}
      </nav>

      <Dialog open={!!renaming} onOpenChange={(o) => !o && setRenaming(null)}>
        <DialogContent>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (renaming && title.trim()) onRename(renaming.id, title.trim());
              setRenaming(null);
            }}
          >
            <DialogHeader><DialogTitle>Rename conversation</DialogTitle></DialogHeader>
            <Input aria-label="Conversation title" className="my-4" value={title} maxLength={120} onChange={(e) => setTitle(e.target.value)} autoFocus />
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setRenaming(null)}>Cancel</Button>
              <Button type="submit" disabled={!title.trim()}>Save</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog open={!!deleting} onOpenChange={(o) => !o && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete this conversation?</AlertDialogTitle>
            <AlertDialogDescription>&ldquo;{deleting?.title}&rdquo; and its messages will be permanently deleted.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => deleting && onDelete(deleting.id)}>Delete</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
