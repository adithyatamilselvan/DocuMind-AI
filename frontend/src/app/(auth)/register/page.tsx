"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useForm } from "react-hook-form";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { TextField } from "@/components/ui/form-field";
import { errorMessage } from "@/lib/api";
import { type RegisterValues, registerSchema } from "@/schemas/auth";
import { authService } from "@/services/auth";

export default function RegisterPage() {
  const router = useRouter();
  const qc = useQueryClient();
  const {
    register,
    handleSubmit,
    setError,
    formState: { errors, isSubmitting },
  } = useForm<RegisterValues>({ resolver: zodResolver(registerSchema) });

  async function onSubmit(values: RegisterValues) {
    try {
      await authService.register(values);
      qc.clear();
      router.replace("/dashboard");
    } catch (e) {
      setError("root", { message: errorMessage(e) });
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle as="h1" className="text-xl">Create your account</CardTitle>
        <CardDescription>A private workspace is created for you.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4" noValidate>
          <TextField label="Name" autoComplete="name" error={errors.name?.message} {...register("name")} />
          <TextField label="Email" type="email" autoComplete="email" error={errors.email?.message} {...register("email")} />
          <TextField
            label="Password"
            type="password"
            autoComplete="new-password"
            hint="At least 10 characters, mixing letters with numbers or symbols."
            error={errors.password?.message}
            {...register("password")}
          />
          {errors.root && (
            <p role="alert" className="text-sm text-destructive">
              {errors.root.message}
            </p>
          )}
          <Button type="submit" className="w-full" size="lg" disabled={isSubmitting}>
            {isSubmitting ? "Creating account…" : "Create account"}
          </Button>
        </form>
        <p className="mt-4 text-center text-sm text-muted-foreground">
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-primary hover:underline">
            Sign in
          </Link>
        </p>
      </CardContent>
    </Card>
  );
}
