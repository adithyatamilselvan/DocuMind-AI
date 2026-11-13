import { describe, expect, it } from "vitest";

import { passwordSchema, registerSchema, resetSchema } from "./auth";

describe("passwordSchema", () => {
  it.each([
    ["short1!", false],
    ["onlyletterslong", false],
    ["1234567890123", false],
    ["correct-horse-9", true],
  ])("%s -> %s", (value, ok) => {
    expect(passwordSchema.safeParse(value).success).toBe(ok);
  });
});

describe("registerSchema", () => {
  it("trims the name and validates email", () => {
    const r = registerSchema.safeParse({ name: "  Ada ", email: "ada@example.com", password: "correct-horse-9" });
    expect(r.success && r.data.name).toBe("Ada");
    expect(registerSchema.safeParse({ name: "A", email: "nope", password: "correct-horse-9" }).success).toBe(false);
  });
});

describe("resetSchema", () => {
  it("requires matching confirmation", () => {
    const r = resetSchema.safeParse({ password: "correct-horse-9", confirm: "different-1234" });
    expect(r.success).toBe(false);
    expect(!r.success && r.error.issues[0].path).toEqual(["confirm"]);
  });
});
