import { z } from "zod";

// Mirrors backend/app/modules/auth/schemas.py (the backend remains authoritative).
export const passwordSchema = z
  .string()
  .min(10, "Use at least 10 characters")
  .max(128, "Use at most 128 characters")
  .refine((v) => !/^[A-Za-z]+$/.test(v) && !/^\d+$/.test(v), "Mix letters with numbers or symbols");

export const loginSchema = z.object({
  email: z.string().email("Enter a valid email"),
  password: z.string().min(1, "Enter your password"),
});

export const registerSchema = z.object({
  name: z.string().trim().min(1, "Enter your name").max(100),
  email: z.string().email("Enter a valid email"),
  password: passwordSchema,
});

export const forgotSchema = z.object({ email: z.string().email("Enter a valid email") });

export const resetSchema = z
  .object({ password: passwordSchema, confirm: z.string() })
  .refine((v) => v.password === v.confirm, { path: ["confirm"], message: "Passwords do not match" });

export const changePasswordSchema = z
  .object({ current_password: z.string().min(1, "Required"), new_password: passwordSchema, confirm: z.string() })
  .refine((v) => v.new_password === v.confirm, { path: ["confirm"], message: "Passwords do not match" });

export type LoginValues = z.infer<typeof loginSchema>;
export type RegisterValues = z.infer<typeof registerSchema>;
