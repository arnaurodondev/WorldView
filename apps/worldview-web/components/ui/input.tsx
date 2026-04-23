/**
 * components/ui/input.tsx — shadcn/ui Input component
 *
 * WHY THIS EXISTS: Used in search boxes (GlobalSearch), transaction forms,
 * screener filter inputs, and settings fields. The dark-theme styling ensures
 * inputs are visible against the Bloomberg Dark background (#0A0E14).
 */

import * as React from "react";
import { cn } from "@/lib/utils";

// WHY type alias not interface: ESLint's no-empty-object-type rule disallows empty interfaces
export type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        className={cn(
          // h-9: compact height for dense forms
          // bg-muted: matches elevated panel background
          "flex h-9 w-full rounded-md border border-border bg-muted px-3 py-1 text-sm shadow-sm transition-colors",
          "file:border-0 file:bg-transparent file:text-sm file:font-medium",
          "placeholder:text-muted-foreground",
          "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
          "disabled:cursor-not-allowed disabled:opacity-50",
          className,
        )}
        ref={ref}
        {...props}
      />
    );
  },
);
Input.displayName = "Input";

export { Input };
