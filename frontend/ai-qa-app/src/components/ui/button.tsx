import * as React from "react"
import { cn } from "@/lib/utils"

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "default" | "outline" | "ghost"
  size?: "sm" | "default" | "lg"
}

function Button({
  ref,
  className,
  variant = "default",
  size = "default",
  ...props
}: ButtonProps & { ref?: React.Ref<HTMLButtonElement> }) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center whitespace-nowrap rounded-lg text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50",
        {
          "bg-blue-600 text-white hover:bg-blue-700 shadow-sm": variant === "default",
          "border border-gray-300 bg-white hover:bg-gray-50 text-gray-700": variant === "outline",
          "hover:bg-gray-100 text-gray-700": variant === "ghost",
        },
        {
          "h-8 px-3 text-xs": size === "sm",
          "h-10 px-4 py-2": size === "default",
          "h-12 px-6 text-base": size === "lg",
        },
        className
      )}
      ref={ref}
      {...props}
    />
  )
}

export { Button }
