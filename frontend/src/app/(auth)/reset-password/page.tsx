"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { TextField } from "@/components/ui/form-field";
import { errorMessage } from "@/lib/api";
import { resetSchema } from "@/schemas/auth";
import { authService } from "@/services/auth";

type Values = z.infer<typeof resetSchema>;

function ResetForm() {
  const router = useRouter();
  const token = useSearchParams().get("token");
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(resetSchema) });

  async function onSubmit({ password }: Values) {
    try {
      await authService.resetPassword({ token: token ?? "", password });
      toast.success("Password updated. Sign in with your new password.");
      router.replace("/login");
    } catch (e) {
      setError("root", { message: errorMessage(e) });
    }
  }

  if (!token) {
    return (
      <Card>
        <CardHeader>
          <CardTitle as="h1" className="text-xl">Link not valid</CardTitle>
          <CardDescription>This reset link is missing its token.</CardDescription>
        </CardHeader>
        <CardContent>
          <Link href="/forgot-password" className="text-sm font-medium text-primary hover:underline">
            Request a new link
          </Link>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle as="h1" className="text-xl">Choose a new password</CardTitle>
        <CardDescription>You will be signed out of all other devices.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <TextField label="New password" type="password" autoComplete="new-password" error={errors.password?.message} {...register("password")} />
          <TextField label="Confirm password" type="password" autoComplete="new-password" error={errors.confirm?.message} {...register("confirm")} />
          {errors.root && (
            <p role="alert" className="text-sm text-destructive">
              {errors.root.message}
            </p>
          )}
          <Button type="submit" className="w-full" size="lg" disabled={isSubmitting}>
            {isSubmitting ? "Saving…" : "Update password"}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense>
      <ResetForm />
    </Suspense>
  );
}
