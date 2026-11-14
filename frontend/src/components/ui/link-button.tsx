import Link from "next/link";
import type { ComponentProps } from "react";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Props = Omit<ComponentProps<typeof Link>, "className"> & {
  className?: string;
  variant?: Parameters<typeof buttonVariants>[0] extends infer P ? (P extends { variant?: infer V } ? V : never) : never;
  size?: Parameters<typeof buttonVariants>[0] extends infer P ? (P extends { size?: infer S } ? S : never) : never;
};

/** A real <a> (role "link") that looks like a Button. Use for navigation instead of
 * `<Button render={<Link/>}>`, which Base UI forces to role="button". */
export function LinkButton({ variant, size, className, ...props }: Props) {
  return <Link className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}

/** Same for plain anchors (downloads, external links). */
export function AnchorButton({
  variant, size, className, ...props
}: Omit<ComponentProps<"a">, "className"> & Pick<Props, "variant" | "size" | "className">) {
  return <a className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}
