import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-lg text-sm font-semibold transition-[background-color,box-shadow,border-color,color,transform] duration-150 active:translate-y-px disabled:pointer-events-none disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-background",
  {
    variants: {
      variant: {
        default:
          "bg-[var(--accent)] text-white shadow-[0_1px_2px_rgba(15,23,42,0.12),0_6px_16px_-6px_rgba(79,70,229,0.5)] hover:bg-[var(--accent-hover)]",
        secondary:
          "border border-[var(--border-strong)] bg-white text-slate-700 shadow-[var(--shadow-xs)] hover:bg-slate-50 hover:text-slate-900",
        ghost: "text-slate-500 hover:bg-slate-100 hover:text-slate-900",
        destructive:
          "bg-[var(--danger)] text-white shadow-[0_1px_2px_rgba(15,23,42,0.12)] hover:bg-rose-600",
      },
      size: {
        default: "h-10 px-4 py-2",
        sm: "h-8 px-3 text-xs",
        icon: "h-10 w-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: ButtonProps) {
  const Comp = asChild ? Slot : "button";

  return <Comp className={cn(buttonVariants({ variant, size, className }))} {...props} />;
}
