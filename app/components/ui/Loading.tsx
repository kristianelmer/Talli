import type { CSSProperties } from "react";

import { cx } from "./cx";
import { Spinner } from "./Spinner";

export function LoadingState({ label = "Laster …" }: { label?: string }) {
  return (
    <div className="loadingState" role="status" aria-live="polite">
      <Spinner />
      <span>{label}</span>
    </div>
  );
}

type SkeletonProps = {
  width?: string | number;
  height?: string | number;
  radius?: string;
  className?: string;
};

export function Skeleton({ width, height, radius, className }: SkeletonProps) {
  const style: CSSProperties = { width, height, borderRadius: radius };
  return (
    <span className={cx("skeleton", className)} style={style} aria-hidden="true" />
  );
}

export function SkeletonText({ lines = 3 }: { lines?: number }) {
  const widths = ["100%", "92%", "70%", "84%", "60%"];
  return (
    <span role="status" aria-label="Laster innhold">
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          className="skeleton--text"
          width={widths[i % widths.length]}
          height="0.9em"
        />
      ))}
    </span>
  );
}
