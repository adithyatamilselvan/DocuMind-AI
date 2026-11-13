"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { PageHeader } from "@/components/page-header";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { TextField } from "@/components/ui/form-field";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { keys, useCurrentWorkspace, useMe } from "@/hooks/use-session";
import { errorMessage } from "@/lib/api";
import { workspaceService } from "@/services/workspaces";
import { atLeast, type Member, type Role } from "@/types";

const ROLES: Role[] = ["viewer", "editor", "admin", "owner"];
const addSchema = z.object({ email: z.string().email("Enter a valid email"), role: z.enum(ROLES) });
type AddValues = z.infer<typeof addSchema>;

export default function WorkspacePage() {
  const qc = useQueryClient();
  const { data: me } = useMe();
  const { workspace } = useCurrentWorkspace();
  const wsId = workspace?.id;
  const isAdmin = atLeast(workspace?.role, "admin");
  const isOwner = workspace?.role === "owner";

  const members = useQuery({
    queryKey: ["members", wsId],
    queryFn: () => workspaceService.members(wsId!),
    enabled: !!wsId,
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["members", wsId] });

  const add = useMutation({
    mutationFn: (v: AddValues) => workspaceService.addMember(wsId!, v),
    onSuccess: () => {
      toast.success("Member added");
      reset({ email: "", role: "viewer" });
      refresh();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const setRole = useMutation({
    mutationFn: ({ userId, role }: { userId: string; role: Role }) =>
      workspaceService.setRole(wsId!, userId, role),
    onSuccess: () => {
      toast.success("Role updated");
      refresh();
    },
    onError: (e) => {
      toast.error(errorMessage(e));
      refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (userId: string) => workspaceService.removeMember(wsId!, userId),
    onSuccess: (_d, userId) => {
      toast.success(userId === me?.id ? "You left the workspace" : "Member removed");
      qc.invalidateQueries({ queryKey: keys.workspaces });
      refresh();
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const { register, handleSubmit, reset, formState: { errors } } = useForm<AddValues>({
    resolver: zodResolver(addSchema),
    defaultValues: { email: "", role: "viewer" },
  });

  return (
    <>
      <PageHeader title="Workspace" description={workspace ? `${workspace.name} · you are ${workspace.role}` : undefined} />

      {isAdmin && (
        <Card className="mb-6">
          <CardHeader>
            <CardTitle>Add a member</CardTitle>
            <CardDescription>The person needs a DocuMind account already.</CardDescription>
          </CardHeader>
          <CardContent>
            <form
              onSubmit={handleSubmit((v) => add.mutate(v))}
              className="flex flex-col gap-3 sm:flex-row sm:items-end"
              noValidate
            >
              <div className="flex-1">
                <TextField label="Email" type="email" error={errors.email?.message} {...register("email")} />
              </div>
              <div className="space-y-1.5">
                <label htmlFor="new-role" className="text-sm font-medium">Role</label>
                <NativeSelect id="new-role" className="block h-9 w-full sm:w-32" {...register("role")}>
                  {ROLES.filter((r) => r !== "owner" || isOwner).map((r) => (
                    <option key={r} value={r}>{r}</option>
                  ))}
                </NativeSelect>
              </div>
              <Button type="submit" size="lg" disabled={add.isPending}>
                {add.isPending ? "Adding…" : "Add member"}
              </Button>
            </form>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Members</CardTitle>
        </CardHeader>
        <CardContent>
          {members.isLoading ? (
            <div className="space-y-2">
              <Skeleton className="h-10" />
              <Skeleton className="h-10" />
            </div>
          ) : members.isError ? (
            <p role="alert" className="text-sm text-destructive">{errorMessage(members.error)}</p>
          ) : (
            <ul className="divide-y">
              {members.data?.map((m) => (
                <MemberRow
                  key={m.user_id}
                  member={m}
                  isSelf={m.user_id === me?.id}
                  canEdit={isAdmin && (isOwner || m.role !== "owner")}
                  isOwner={isOwner}
                  onRole={(role) => setRole.mutate({ userId: m.user_id, role })}
                  onRemove={() => remove.mutate(m.user_id)}
                />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </>
  );
}

function MemberRow({
  member, isSelf, canEdit, isOwner, onRole, onRemove,
}: {
  member: Member; isSelf: boolean; canEdit: boolean; isOwner: boolean;
  onRole: (r: Role) => void; onRemove: () => void;
}) {
  return (
    <li className="flex flex-wrap items-center gap-3 py-3">
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">
          {member.name} {isSelf && <Badge variant="outline" className="ml-1">You</Badge>}
        </p>
        <p className="truncate text-xs text-muted-foreground">{member.email}</p>
      </div>
      {canEdit ? (
        <NativeSelect
          aria-label={`Role for ${member.name}`}
          value={member.role}
          onChange={(e) => onRole(e.target.value as Role)}
        >
          {ROLES.filter((r) => r !== "owner" || isOwner).map((r) => (
            <option key={r} value={r}>{r}</option>
          ))}
        </NativeSelect>
      ) : (
        <Badge variant="secondary" className="capitalize">{member.role}</Badge>
      )}
      {(canEdit || isSelf) && (
        <AlertDialog>
          <AlertDialogTrigger
            render={<Button variant="ghost" size="icon" aria-label={isSelf ? "Leave workspace" : `Remove ${member.name}`} />}
          >
            <Trash2 className="size-4" aria-hidden />
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{isSelf ? "Leave this workspace?" : `Remove ${member.name}?`}</AlertDialogTitle>
              <AlertDialogDescription>
                {isSelf ? "You will lose access to its documents." : "They will immediately lose access to this workspace."}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction variant="destructive" onClick={onRemove}>
                {isSelf ? "Leave" : "Remove"}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      )}
    </li>
  );
}
