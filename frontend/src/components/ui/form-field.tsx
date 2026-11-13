import * as React from "react";

import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

type Props = React.ComponentProps<typeof Input> & {
  label: string;
  error?: string;
  hint?: string;
};

/** Label + input + accessible error message, for use with react-hook-form's `register`. */
export const TextField = React.forwardRef<HTMLInputElement, Props>(function TextField(
  { label, error, hint, id, ...props },
  ref,
) {
  const autoId = React.useId();
  const fieldId = id ?? autoId;
  const describedBy = error ? `${fieldId}-error` : hint ? `${fieldId}-hint` : undefined;
  return (
    <div className="space-y-1.5">
      <Label htmlFor={fieldId}>{label}</Label>
      <Input
        id={fieldId}
        ref={ref}
        aria-invalid={!!error}
        aria-describedby={describedBy}
        {...props}
      />
      {error ? (
        <p id={`${fieldId}-error`} role="alert" className="text-xs text-destructive">
          {error}
        </p>
      ) : hint ? (
        <p id={`${fieldId}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
});
