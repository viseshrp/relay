import * as React from "react";

import { cn } from "@/lib/utils";

type ButtonVariant = "default" | "secondary" | "ghost" | "destructive";

const variantClasses: Record<ButtonVariant, string> = {
  default: "bg-primary text-primary-foreground hover:opacity-90",
  secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
  ghost: "bg-transparent text-foreground hover:bg-secondary/60",
  destructive: "bg-destructive text-destructive-foreground hover:opacity-90",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(({ className, variant = "default", asChild = false, children, ...props }, ref) => {
  const mergedClassName = cn(
    "inline-flex items-center justify-center rounded-full px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50",
    variantClasses[variant],
    className,
  );

  if (asChild && React.isValidElement(children)) {
    return React.cloneElement(children, {
      className: cn(mergedClassName, (children.props as { className?: string }).className),
    });
  }

  return (
    <button ref={ref} className={mergedClassName} {...props}>
      {children}
    </button>
  );
});

Button.displayName = "Button";
