import type { FilingReadinessSnapshotRow, FilingSubmissionRow, NotificationOutboxRow } from "./supabase/server";

export type FilingDeadlineStatus = "upcoming" | "due" | "overdue" | "simulated" | "late_simulated";
export type DeadlineFiling = "aksjonærregisteroppgaven" | "skattemelding for AS" | "årsregnskap";

export type FilingDeadline = {
  filing: DeadlineFiling;
  incomeYear: number;
  deadline: string;
  status: FilingDeadlineStatus;
  message: string;
};

export type DeadlineReminderPreference = {
  filing: DeadlineFiling;
  enabled: boolean;
  leadDays: number[];
};

export type DeadlineReminderCandidate = {
  filing: DeadlineFiling;
  obligation: FilingReadinessSnapshotRow["obligation"];
  incomeYear: number;
  deadline: string;
  daysUntilDeadline: number;
  reminderKind: "upcoming" | "due" | "overdue";
  dedupeKey: string;
  shouldQueue: boolean;
  skipReason: string | null;
  subject: string;
  body: string;
  readinessPath: string;
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

export function buildDeadlineReminderPlan(input: {
  incomeYear: number;
  recipientEmail: string;
  submissions: Pick<
    FilingSubmissionRow,
    "filing" | "income_year" | "mode" | "receipt_id" | "created_at" | "preview_confirmed_at"
  >[];
  readinessSnapshots: Pick<
    FilingReadinessSnapshotRow,
    "obligation" | "income_year" | "ready" | "hard_blocks" | "status"
  >[];
  notifications: Pick<NotificationOutboxRow, "template" | "payload" | "status">[];
  preferences?: DeadlineReminderPreference[];
  today?: Date;
}): DeadlineReminderCandidate[] {
  const today = normalizeDate(input.today ?? new Date());
  const dashboard = buildDeadlineDashboard({ incomeYear: input.incomeYear, submissions: input.submissions, today });
  const preferences = input.preferences ?? defaultReminderPreferences();
  return dashboard.map((deadline) => {
    const obligation = obligationForFiling(deadline.filing);
    const preference = preferences.find((item) => item.filing === deadline.filing) ?? {
      filing: deadline.filing,
      enabled: true,
      leadDays: [30, 7, 1, 0, -1],
    };
    const deadlineDate = normalizeDate(new Date(`${deadline.deadline}T00:00:00Z`));
    const daysUntilDeadline = Math.round((deadlineDate.getTime() - today.getTime()) / 86_400_000);
    const reminderKind = daysUntilDeadline > 0 ? "upcoming" : daysUntilDeadline === 0 ? "due" : "overdue";
    const dedupeKey = `deadline:${input.incomeYear}:${deadline.filing}:${reminderKind}:${deadline.deadline}`;
    const readiness = input.readinessSnapshots.find(
      (snapshot) => snapshot.income_year === input.incomeYear && snapshot.obligation === obligation,
    );
    const unsupported = readiness?.hard_blocks?.some((issue) =>
      ["unsupported_entity", "tax_return_unclear_fritaksmetoden", "tax_return_shareholder_loan_review_required", "rf1086_preview_not_ready"].includes(issue.code),
    );
    const duplicate = input.notifications.some(
      (notification) =>
        notification.template === "deadline_reminder" &&
        ["queued", "sent"].includes(notification.status) &&
        notification.payload?.dedupeKey === dedupeKey,
    );
    const inWindow = preference.leadDays.includes(daysUntilDeadline) || (daysUntilDeadline < 0 && preference.leadDays.includes(-1));
    const completed = deadline.status === "simulated" || deadline.status === "late_simulated";
    const skipReason = !preference.enabled
      ? "opted_out"
      : completed
        ? "already_completed"
        : duplicate
          ? "duplicate"
          : unsupported
            ? "unsupported_case"
            : !inWindow
              ? "outside_reminder_window"
              : null;
    return {
      filing: deadline.filing,
      obligation,
      incomeYear: input.incomeYear,
      deadline: deadline.deadline,
      daysUntilDeadline,
      reminderKind,
      dedupeKey,
      shouldQueue: skipReason === null,
      skipReason,
      subject: deadlineReminderSubject(deadline.filing, input.incomeYear, reminderKind),
      body: deadlineReminderBody(deadline.filing, input.incomeYear, deadline.deadline, reminderKind, readiness?.ready ?? false),
      readinessPath: `/#readiness-${obligation}-${input.incomeYear}`,
    };
  });
}

export function defaultReminderPreferences(): DeadlineReminderPreference[] {
  return filingDeadlines.map((deadline) => ({
    filing: deadline.filing,
    enabled: true,
    leadDays: [30, 7, 1, 0, -1],
  }));
}

export function obligationForFiling(filing: DeadlineFiling): FilingReadinessSnapshotRow["obligation"] {
  const obligations: Record<DeadlineFiling, FilingReadinessSnapshotRow["obligation"]> = {
    aksjonærregisteroppgaven: "aksjonaerregisteroppgaven",
    "skattemelding for AS": "skattemelding",
    årsregnskap: "aarsregnskap",
  };
  return obligations[filing];
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

function deadlineReminderSubject(filing: DeadlineFiling, incomeYear: number, kind: DeadlineReminderCandidate["reminderKind"]) {
  const prefix = kind === "overdue" ? "Forfalt frist" : kind === "due" ? "Frist i dag" : "Kommende frist";
  return `${prefix}: ${filing} ${incomeYear}`;
}

function deadlineReminderBody(
  filing: DeadlineFiling,
  incomeYear: number,
  deadline: string,
  kind: DeadlineReminderCandidate["reminderKind"],
  ready: boolean,
) {
  const status = ready ? "Readiness viser klar status." : "Readiness viser åpne punkter som må kontrolleres.";
  const timing =
    kind === "overdue"
      ? "Fristen er passert. Send inn så snart grunnlaget er klart. Talli kan ikke garantere gebyrfri eller sanksjonsfri behandling etter frist."
      : kind === "due"
        ? "Frist i dag. Kontroller grunnlag, tilgang og innsending før du sender."
        : "Fristen nærmer seg. Kontroller grunnlag, dokumentasjon og tilgang i god tid.";
  return `${filing} for inntektsåret ${incomeYear} har frist ${deadline}. ${status} ${timing}`;
}
