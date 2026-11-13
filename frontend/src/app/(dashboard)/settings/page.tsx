"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTheme } from "next-themes";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { TextField } from "@/components/ui/form-field";
import { NativeSelect } from "@/components/ui/native-select";
import { Skeleton } from "@/components/ui/skeleton";
import { keys, useCurrentWorkspace, useMe } from "@/hooks/use-session";
import { errorMessage } from "@/lib/api";
import { changePasswordSchema } from "@/schemas/auth";
import { authService } from "@/services/auth";
import { workspaceService } from "@/services/workspaces";
import { atLeast } from "@/types";

const profileSchema = z.object({ name: z.string().trim().min(1, "Enter your name").max(100) });
type PasswordValues = z.infer<typeof changePasswordSchema>;

export default function SettingsPage() {
  const qc = useQueryClient();
  const { data: user } = useMe();
  const { workspace } = useCurrentWorkspace();
  const { theme, setTheme } = useTheme();

  const profile = useForm<z.infer<typeof profileSchema>>({
    resolver: zodResolver(profileSchema),
    values: { name: user?.name ?? "" },
  });
  const saveProfile = useMutation({
    mutationFn: (v: { name: string }) => authService.updateProfile(v),
    onSuccess: () => {
      toast.success("Profile saved");
      qc.invalidateQueries({ queryKey: keys.me });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const resend = useMutation({
    mutationFn: authService.resendVerification,
    onSuccess: () => toast.success("Verification email sent"),
    onError: (e) => toast.error(errorMessage(e)),
  });

  const pw = useForm<PasswordValues>({ resolver: zodResolver(changePasswordSchema) });
  const changePw = useMutation({
    mutationFn: (v: PasswordValues) =>
      authService.changePassword({ current_password: v.current_password, new_password: v.new_password }),
    onSuccess: () => {
      toast.success("Password changed. Other devices were signed out.");
      pw.reset();
    },
    onError: (e) => pw.setError("root", { message: errorMessage(e) }),
  });

  const consent = useMutation({
    mutationFn: (value: boolean) =>
      workspaceService.update(workspace!.id, { settings: { ai_processing_consent: value } }),
    onSuccess: () => {
      toast.success("Workspace AI setting updated");
      qc.invalidateQueries({ queryKey: keys.workspaces });
    },
    onError: (e) => toast.error(errorMessage(e)),
  });

  if (!user) return <Skeleton className="h-64" />;
  const isAdmin = atLeast(workspace?.role, "admin");
  const consented = workspace?.settings?.ai_processing_consent === true;

  return (
    <>
      <PageHeader title="Settings" description="Manage your profile, security and workspace preferences." />
      <div className="grid max-w-2xl gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Profile</CardTitle>
            <CardDescription className="flex items-center gap-2">
              {user.email}
              <Badge variant={user.email_verified ? "secondary" : "outline"}>
                {user.email_verified ? "Verified" : "Unverified"}
              </Badge>
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={profile.handleSubmit((v) => saveProfile.mutate(v))} className="space-y-4" noValidate>
              <TextField label="Name" error={profile.formState.errors.name?.message} {...profile.register("name")} />
              <div className="flex gap-2">
                <Button type="submit" disabled={saveProfile.isPending}>Save</Button>
                {!user.email_verified && (
                  <Button type="button" variant="outline" disabled={resend.isPending} onClick={() => resend.mutate()}>
                    Resend verification email
                  </Button>
                )}
              </div>
            </form>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Appearance</CardTitle>
            <CardDescription>Choose how DocuMind looks on this device.</CardDescription>
          </CardHeader>
          <CardContent>
            <label htmlFor="theme" className="mb-1.5 block text-sm font-medium">Theme</label>
            <NativeSelect id="theme" className="h-9 w-40" value={theme ?? "system"} onChange={(e) => setTheme(e.target.value)}>
              <option value="system">System</option>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
            </NativeSelect>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Security</CardTitle>
            <CardDescription>Changing your password signs you out of all other devices.</CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={pw.handleSubmit((v) => changePw.mutate(v))} className="space-y-4" noValidate>
              <TextField label="Current password" type="password" autoComplete="current-password" error={pw.formState.errors.current_password?.message} {...pw.register("current_password")} />
              <TextField label="New password" type="password" autoComplete="new-password" error={pw.formState.errors.new_password?.message} {...pw.register("new_password")} />
              <TextField label="Confirm new password" type="password" autoComplete="new-password" error={pw.formState.errors.confirm?.message} {...pw.register("confirm")} />
              {pw.formState.errors.root && (
                <p role="alert" className="text-sm text-destructive">{pw.formState.errors.root.message}</p>
              )}
              <Button type="submit" disabled={changePw.isPending}>Change password</Button>
            </form>
          </CardContent>
        </Card>

        {workspace && (
          <Card>
            <CardHeader>
              <CardTitle>Privacy and AI processing</CardTitle>
              <CardDescription>
                Workspace: {workspace.name}. When enabled, text extracted from this workspace&apos;s documents is
                sent to the external AI provider configured by the server operator for summaries, search and answers.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <label className="flex items-start gap-3 text-sm">
                <input
                  type="checkbox"
                  className="mt-0.5 size-4 accent-[var(--primary)]"
                  checked={consented}
                  disabled={!isAdmin || consent.isPending}
                  onChange={(e) => consent.mutate(e.target.checked)}
                />
                <span>
                  Allow external AI processing of document content in this workspace
                  {!isAdmin && <span className="block text-xs text-muted-foreground">Only workspace admins can change this.</span>}
                </span>
              </label>
            </CardContent>
          </Card>
        )}
      </div>
    </>
  );
}
