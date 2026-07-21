import type { ButtonHTMLAttributes, ReactNode } from "react";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "regular" | "small" | "icon";
  icon?: ReactNode;
};

export function Button({
  variant = "secondary",
  size = "regular",
  icon,
  className = "",
  children,
  ...props
}: ButtonProps) {
  return (
    <button className={`button button--${variant} button--${size} ${className}`} {...props}>
      {icon}
      {children}
    </button>
  );
}
