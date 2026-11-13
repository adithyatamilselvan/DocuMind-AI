"use client";

import { useQuery } from "@tanstack/react-query";
import { ShieldCheck, ShieldOff, Users } from "lucide-react";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentWorkspace, useMe } from "@/hooks/use-session";
import { workspaceService } from "@/services/workspaces";

export default function DashboardPage() {
  const { data: user } = useMe();
  const { workspace, isLoading } = useCurrentWorkspace();
  const members = useQuery({
    queryKey: ["members", workspace?.id],
    queryFn: () => workspaceService.members(workspace!.id),
    enabled: !!workspace,
  });

  if (isLoading || !workspace) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-8 w-64" />
        <div className="grid gap-4 sm:grid-cols-3">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      </div>
    );
  }

  const consent = workspace.settings?.ai_processing_consent === true;
  return (
    <>
      <PageHeader
        title={`Welcome${user ? `, ${user.name.split(" ")[0]}` : ""}`}
        description={`You are working in ${workspace.name}.`}
      />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardDescription>Your role</CardDescription>
            <CardTitle className="text-2xl capitalize">{workspace.role}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription className="flex items-center gap-1.5">
              <Users className="size-3.5" aria-hidden /> Members
            </CardDescription>
            <CardTitle className="text-2xl">
              {members.isLoading ? <Skeleton className="h-7 w-10" /> : (members.data?.length ?? "—")}
            </CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>AI processing consent</CardDescription>
            <CardTitle className="flex items-center gap-2 text-base">
              {consent ? (
                <ShieldCheck className="size-4 text-success" aria-hidden />
              ) : (
                <ShieldOff className="size-4 text-warning" aria-hidden />
              )}
              <Badge variant={consent ? "secondary" : "outline"}>{consent ? "Granted" : "Not granted"}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent className="text-xs text-muted-foreground">
            Document text is only sent to external AI providers after an admin grants consent in Settings.
          </CardContent>
        </Card>
      </div>
    </>
  );
}
