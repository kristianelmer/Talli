import type { FilingSubmissionRow } from "./supabase/server";

export type FilingDeadlineStatus = "upcoming" | "due" | "overdue" | "simulated" | "late_simulated";

export type FilingDeadline = {
  filing: "aksjonærregisteroppgaven" | "skattemelding for AS" | "årsregnskap";
  incomeYear: number;
  deadline: string;
  status: FilingDeadlineStatus;
  message: string;
};

const filingDeadlines = [
  { filing: "aksjonærregisteroppgaven", month: 0, day: 31 },
  { filing: "skattemelding for AS", month: 4, day: 31 },
  { filing: "årsregnskap", month: 6, day: 31 },
] as const;

export function buildDeadlineDashboard(input: {
  incomeYear: number;
  submissions: Pick<
    FilingSubmissionRow,
    "filing" | "income_year" | "mode" | "receipt_id" | "created_at" | "preview_confirmed_at"
  >[];
  today?: Date;
}): FilingDeadline[] {
  const today = normalizeDate(input.today ?? new Date());
  return filingDeadlines.map((item) => {
    const deadline = new Date(Date.UTC(input.incomeYear + 1, item.month, item.day));
    const submission = input.submissions.find(
      (candidate) =>
        candidate.income_year === input.incomeYear &&
        candidate.filing === item.filing &&
        candidate.mode === "simulation" &&
        candidate.receipt_id,
    );
    if (submission) {
      const filedAt = normalizeDate(new Date(submission.preview_confirmed_at ?? submission.created_at));
      const late = filedAt.getTime() > deadline.getTime();
      return {
        filing: item.filing,
        incomeYear: input.incomeYear,
        deadline: formatDate(deadline),
        status: late ? "late_simulated" : "simulated",
        message: late
          ? "Simulert kvittering finnes, men den ble arkivert etter fristen."
          : "Simulert kvittering er arkivert for denne fristen.",
      };
    }
    if (today.getTime() === deadline.getTime()) {
      return {
        filing: item.filing,
        incomeYear: input.incomeYear,
        deadline: formatDate(deadline),
        status: "due",
        message: "Frist i dag. Kontroller grunnlag og send inn ved behov.",
      };
    }
    if (today.getTime() > deadline.getTime()) {
      return {
        filing: item.filing,
        incomeYear: input.incomeYear,
        deadline: formatDate(deadline),
        status: "overdue",
        message: "Fristen er passert. Avklar status og send inn så snart som mulig.",
      };
    }
    return {
      filing: item.filing,
      incomeYear: input.incomeYear,
      deadline: formatDate(deadline),
      status: "upcoming",
      message: "Fristen kommer senere.",
    };
  });
}

export function deadlineStatusLabel(status: FilingDeadlineStatus) {
  return {
    upcoming: "Kommer",
    due: "I dag",
    overdue: "Forfalt",
    simulated: "Simulert",
    late_simulated: "Simulert etter frist",
  }[status];
}

function normalizeDate(date: Date) {
  return new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
}

function formatDate(date: Date) {
  return date.toISOString().slice(0, 10);
}
