"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { AnchorButton } from "@/components/ui/link-button";
import { Input } from "@/components/ui/input";
import { useCurrentWorkspace } from "@/hooks/use-session";
import { ApiError, errorMessage } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { governanceService } from "@/services/governance";
import { atLeast } from "@/types";

export function UsageCard() {
  const { workspace } = useCurrentWorkspace();
  const ws = workspace?.id;
  const q = useQuery({ queryKey: ["usage", ws], queryFn: () => governanceService.usage(ws!), enabled: !!ws && atLeast(workspace?.role, "admin") });
  if (!atLeast(workspace?.role, "admin")) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>AI usage (30 days)</CardTitle>
        <CardDescription>Requests and tokens recorded for this workspace.</CardDescription>
      </CardHeader>
      <CardContent className="text-sm">
        {q.isLoading ? "Loading…" : q.isError ? <span role="alert" className="text-destructive">{errorMessage(q.error)}</span> : q.data && q.data.totals.length === 0 ? (
          <p className="text-muted-foreground">No AI usage recorded yet.</p>
        ) : q.data ? (
          <>
            <p className="mb-2">{formatNumber(q.data.requests)} requests · {formatNumber(q.data.tokens_in)} input / {formatNumber(q.data.tokens_out)} output tokens</p>
            <ul className="divide-y">
              {q.data.totals.map((r) => (
                <li key={`${r.kind}${r.provider}${r.model}`} className="flex justify-between gap-3 py-1.5">
                  <span>{r.kind} <span className="text-xs text-muted-foreground">{r.provider}/{r.model}</span></span>
                  <span className="tabular-nums text-muted-foreground">{formatNumber(r.requests)}</span>
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function PrivacyCard() {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [password, setPassword] = useState("");
  const del = useMutation({
    mutationFn: () => governanceService.deleteAccount(password),
    onSuccess: () => router.replace("/login"),
    onError: (e) => toast.error(e instanceof ApiError && e.code === "owns_shared_workspaces" ? "You own workspaces with other members. Make another member an owner first." : errorMessage(e)),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Your data</CardTitle>
        <CardDescription>Download everything stored about you, or permanently delete your account.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <AnchorButton variant="outline" href={governanceService.exportUrl} download>Export my data (JSON)</AnchorButton>
        {!confirming ? (
          <Button variant="destructive" onClick={() => setConfirming(true)}>Delete account…</Button>
        ) : (
          <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); del.mutate(); }}>
            <p className="text-sm text-muted-foreground">This permanently deletes your account and any workspace where you are the only member, including its documents and files.</p>
            <Input type="password" aria-label="Confirm your password" placeholder="Your password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
            <div className="flex gap-2">
              <Button type="submit" variant="destructive" disabled={!password || del.isPending}>Permanently delete</Button>
              <Button type="button" variant="outline" onClick={() => { setConfirming(false); setPassword(""); }}>Cancel</Button>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
