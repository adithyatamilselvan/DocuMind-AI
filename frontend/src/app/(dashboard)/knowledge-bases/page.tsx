"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Library } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";

import { EmptyState } from "@/components/empty-state";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentWorkspace } from "@/hooks/use-session";
import { errorMessage } from "@/lib/api";
import { knowledgeService } from "@/services/knowledge";
import { atLeast } from "@/types";

export default function KnowledgeBasesPage() {
  const qc = useQueryClient();
  const { workspace } = useCurrentWorkspace();
  const ws = workspace?.id;
  const canEdit = atLeast(workspace?.role, "editor");
  const [name, setName] = useState("");
  const list = useQuery({ queryKey: ["kbs", ws], queryFn: () => knowledgeService.list(ws!), enabled: !!ws });
  const create = useMutation({
    mutationFn: () => knowledgeService.create(ws!, name.trim()),
    onSuccess: () => { setName(""); qc.invalidateQueries({ queryKey: ["kbs", ws] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });

  return (
    <>
      <PageHeader title="Knowledge bases" description="Group documents to search and ask questions within a focused set." />
      {canEdit && (
        <form className="mb-6 flex max-w-md gap-2" onSubmit={(e) => { e.preventDefault(); if (name.trim()) create.mutate(); }}>
          <Input aria-label="Knowledge base name" placeholder="New knowledge base name" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
          <Button type="submit" disabled={!name.trim() || create.isPending}>Create</Button>
        </form>
      )}
      {list.isLoading ? <Skeleton className="h-32" /> : list.isError ? (
        <p role="alert" className="text-sm text-destructive">{errorMessage(list.error)}</p>
      ) : list.data?.length ? (
        <div className="grid gap-4 md:grid-cols-2">
          {list.data.map((kb) => (
            <Card key={kb.id}>
              <CardHeader>
                <CardTitle className="text-base"><Link href={`/knowledge-bases/${kb.id}`} className="hover:underline">{kb.name}</Link></CardTitle>
                <CardDescription>{kb.description || "No description"}</CardDescription>
              </CardHeader>
              <CardContent className="flex items-center gap-2 text-sm">
                <Badge variant="secondary">{kb.document_count} document{kb.document_count === 1 ? "" : "s"}</Badge>
                <Badge variant="outline">{kb.index_status}</Badge>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : (
        <EmptyState icon={Library} title="No knowledge bases yet" description="Create one, then add documents to it." />
      )}
    </>
  );
}
