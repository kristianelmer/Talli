import { cx } from "./cx";

type SpinnerProps = {
  size?: "sm" | "md" | "lg";
  className?: string;
  /** Accessible label; omit when the spinner is decorative inside a labelled control. */
  label?: string;
};

export function Spinner({ size = "md", className, label }: SpinnerProps) {
  return (
    <span
      className={cx("spinner", size !== "md" && `spinner--${size}`, className)}
      role={label ? "status" : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
    />
  );
}
