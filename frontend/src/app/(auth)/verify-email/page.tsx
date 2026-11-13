"use client";

import { useMutation } from "@tanstack/react-query";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef } from "react";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { authService } from "@/services/auth";

function Verify() {
  const token = useSearchParams().get("token");
  const started = useRef(false);
  const mutation = useMutation({ mutationFn: (t: string) => authService.verifyEmail(t) });

  useEffect(() => {
    if (token && !started.current) {
      started.current = true;
      mutation.mutate(token);
    }
  }, [token, mutation]);

  let title = "Verifying your email…";
  let body: React.ReactNode = <Skeleton className="h-4 w-40" />;
  if (!token || mutation.isError) {
    title = "Link not valid";
    body = <p className="text-sm text-muted-foreground">This verification link is invalid or has expired. Sign in and request a new one from Settings.</p>;
  } else if (mutation.isSuccess) {
    title = "Email verified";
    body = <p className="text-sm text-muted-foreground">Thanks, your email address is confirmed.</p>;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle as="h1" className="text-xl">{title}</CardTitle>
        <CardDescription className="sr-only">Email verification status</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4" aria-live="polite">
        {body}
        <Link href="/dashboard" className="text-sm font-medium text-primary hover:underline">
          Continue to DocuMind
        </Link>
      </CardContent>
    </Card>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <Verify />
    </Suspense>
  );
}
