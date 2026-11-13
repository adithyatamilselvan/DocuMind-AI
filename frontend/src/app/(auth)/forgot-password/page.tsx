"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { TextField } from "@/components/ui/form-field";
import { errorMessage } from "@/lib/api";
import { forgotSchema } from "@/schemas/auth";
import { authService } from "@/services/auth";

type Values = z.infer<typeof forgotSchema>;

export default function ForgotPasswordPage() {
  const [sent, setSent] = useState(false);
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<Values>({ resolver: zodResolver(forgotSchema) });

  async function onSubmit({ email }: Values) {
    try {
      await authService.forgotPassword(email);
      setSent(true);
    } catch (e) {
      setError("root", { message: errorMessage(e) });
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle as="h1" className="text-xl">Reset your password</CardTitle>
        <CardDescription>We will email you a link if an account exists.</CardDescription>
      </CardHeader>
      <CardContent>
        {sent ? (
          <p role="status" className="text-sm">
            If an account exists for that address, a reset link is on its way. It expires in one hour.
          </p>
        ) : (
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
            <TextField label="Email" type="email" autoComplete="email" error={errors.email?.message} {...register("email")} />
            {errors.root && (
              <p role="alert" className="text-sm text-destructive">
                {errors.root.message}
              </p>
            )}
            <Button type="submit" className="w-full" size="lg" disabled={isSubmitting}>
              {isSubmitting ? "Sending…" : "Send reset link"}
            </Button>
          </form>
        )}
        <p className="mt-4 text-center text-sm">
          <Link href="/login" className="text-muted-foreground hover:text-foreground">
            Back to sign in
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}
