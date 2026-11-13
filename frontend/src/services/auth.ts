import { api } from "@/lib/api";
import type { User } from "@/types";

export const authService = {
  me: () => api<User>("/auth/me"),
  login: (body: { email: string; password: string }) => api<User>("/auth/login", { body }),
  register: (body: { email: string; password: string; name: string }) =>
    api<User>("/auth/register", { body }),
  logout: () => api("/auth/logout", { method: "POST" }),
  forgotPassword: (email: string) => api("/auth/forgot-password", { body: { email } }),
  resetPassword: (body: { token: string; password: string }) =>
    api("/auth/reset-password", { body }),
  verifyEmail: (token: string) => api("/auth/verify-email", { body: { token } }),
  resendVerification: () => api("/auth/resend-verification", { method: "POST" }),
  updateProfile: (body: {
    name?: string;
    preferences?: { theme: string; notifications_email: boolean };
  }) => api<User>("/users/me", { method: "PATCH", body }),
  changePassword: (body: { current_password: string; new_password: string }) =>
    api("/users/me/password", { body }),
};
