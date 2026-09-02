import {
  createMarketingEventHandler,
  createMarketingWithdrawalHandler,
  marketingMeasurementTransportFromEnvironment,
  type MarketingEventRecorder,
  type MarketingSessionWithdrawer,
} from "../../../features/public-acquisition/server.ts";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const backendRecorder: MarketingEventRecorder = {
  async record(event) {
    return marketingMeasurementTransportFromEnvironment().record(event);
  },
};

const backendWithdrawer: MarketingSessionWithdrawer = {
  async withdraw(anonymousSessionId) {
    return marketingMeasurementTransportFromEnvironment().withdraw(anonymousSessionId);
  },
};

const expectedOrigin = process.env.TALLI_PUBLIC_ORIGIN ?? "https://talli.no";

export const POST = createMarketingEventHandler({
  expectedOrigin,
  recorder: backendRecorder,
  withdrawer: backendWithdrawer,
});

export const DELETE = createMarketingWithdrawalHandler({
  expectedOrigin,
  withdrawer: backendWithdrawer,
});
