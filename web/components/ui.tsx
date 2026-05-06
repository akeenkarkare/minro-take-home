import * as React from "react";
import { cn } from "@/lib/cn";

export function Card({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-background shadow-sm",
        className
      )}
      {...props}
    />
  );
}

export function CardHeader({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5 border-b border-border", className)} {...props} />;
}

export function CardBody({
  className,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("p-5", className)} {...props} />;
}

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "default" | "ghost" | "outline";
};

export function Button({
  className,
  variant = "default",
  ...props
}: ButtonProps) {
  const base =
    "inline-flex items-center justify-center rounded-md text-sm font-medium transition-colors disabled:pointer-events-none disabled:opacity-50 px-4 py-2";
  const styles = {
    default: "bg-foreground text-background hover:bg-foreground/90",
    ghost: "hover:bg-accent",
    outline: "border border-border bg-background hover:bg-accent",
  }[variant];
  return <button className={cn(base, styles, className)} {...props} />;
}

export function Input({
  className,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      className={cn(
        "flex h-10 w-full rounded-md border border-border bg-background px-3 py-2 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-foreground/10",
        className
      )}
      {...props}
    />
  );
}

export function Label({
  className,
  ...props
}: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return (
    <label
      className={cn("text-sm font-medium text-foreground", className)}
      {...props}
    />
  );
}

export function Badge({
  className,
  children,
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border border-border bg-accent px-2.5 py-0.5 text-xs font-medium text-foreground",
        className
      )}
    >
      {children}
    </span>
  );
}

/** Renders a confidence score 0..1 as a colored badge. */
export function ConfidenceBadge({ value }: { value: number }) {
  const color =
    value >= 0.7
      ? "bg-emerald-50 text-emerald-700 border-emerald-200"
      : value >= 0.5
        ? "bg-amber-50 text-amber-700 border-amber-200"
        : value > 0
          ? "bg-orange-50 text-orange-700 border-orange-200"
          : "bg-zinc-50 text-zinc-500 border-zinc-200";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-mono",
        color
      )}
    >
      {value.toFixed(2)}
    </span>
  );
}
