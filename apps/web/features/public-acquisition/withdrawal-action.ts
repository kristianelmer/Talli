"use server";

import { marketingMeasurementTransportFromEnvironment } from "./server.ts";

const uuidV4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/u;

export async function withdrawMarketingMeasurementAction(
  anonymousSessionId: string,
): Promise<boolean> {
  if (!uuidV4.test(anonymousSessionId)) return false;
  try {
    await marketingMeasurementTransportFromEnvironment().withdraw(anonymousSessionId);
    return true;
  } catch {
    return false;
  }
}
