import { cx } from "./cx";
import { Check } from "./Icons";

export type StepItem = { label: string };

type StepperProps = {
  steps: Array<string | StepItem>;
  /** Zero-based index of the current step. */
  current: number;
  className?: string;
};

/** Numbered progress stepper. Horizontal on desktop, vertical on mobile. */
export function Stepper({ steps, current, className }: StepperProps) {
  const items = steps.map((step) =>
    typeof step === "string" ? { label: step } : step,
  );
  const total = items.length;
  const position = Math.min(Math.max(current, 0), total - 1) + 1;

  return (
    <div className={cx("stepper", className)}>
      <span className="stepperCount">
        Steg {position} av {total}
      </span>
      <ol className="stepperList">
        {items.map((item, index) => {
          const state =
            index < current ? "done" : index === current ? "current" : "upcoming";
          return (
            <li
              key={item.label + index}
              className={cx("step", `step--${state}`)}
              aria-current={state === "current" ? "step" : undefined}
            >
              <span className="stepDot">
                {state === "done" ? (
                  <Check size={14} aria-hidden="true" />
                ) : (
                  index + 1
                )}
              </span>
              <span className="stepLabel">{item.label}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
