import type { ReactNode } from "react";

import { cx } from "./cx";
import { Stepper, type StepItem } from "./Stepper";

type WizardShellProps = {
  title: ReactNode;
  intro?: ReactNode;
  steps?: Array<string | StepItem>;
  current?: number;
  /** Back control (e.g. a secondary Button/LinkButton). */
  back?: ReactNode;
  /** Forward control (e.g. a SubmitButton "Lagre og fortsett"). */
  next?: ReactNode;
  children: ReactNode;
  className?: string;
};

/**
 * Centered reading-width wizard container: optional stepper, a head with one
 * decision's title/intro, the step body, and a back/continue footer.
 */
export function WizardShell({
  title,
  intro,
  steps,
  current = 0,
  back,
  next,
  children,
  className,
}: WizardShellProps) {
  return (
    <section className={cx("wizard", className)}>
      {steps ? <Stepper steps={steps} current={current} /> : null}
      <header className="wizardHead">
        <h1 className="wizardTitle">{title}</h1>
        {intro ? <p className="wizardIntro">{intro}</p> : null}
      </header>
      <div className="wizardBody">{children}</div>
      {back || next ? (
        <footer className="wizardFooter">
          <div>{back}</div>
          <div>{next}</div>
        </footer>
      ) : null}
    </section>
  );
}
