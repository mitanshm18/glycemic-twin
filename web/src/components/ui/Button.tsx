import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cx } from "@/lib/cx";

type Variant = "default" | "primary" | "ghost";
type Size = "sm" | "md" | "lg";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: boolean;
  block?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "default", size = "md", icon, block, className, type = "button", ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      className={cx(
        "btn",
        variant !== "default" && `btn--${variant}`,
        size !== "md" && `btn--${size}`,
        icon && "btn--icon",
        block && "btn--block",
        className,
      )}
      {...rest}
    />
  );
});
