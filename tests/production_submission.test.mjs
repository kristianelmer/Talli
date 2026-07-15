import assert from "node:assert/strict";
import test from "node:test";

import {
  classifyRf1086TransportOutcome,
  transitionProductionSubmission,
} from "../app/lib/production-submission.ts";

test("allows only documented production submission transitions", () => {
  assert.equal(transitionProductionSubmission("approved", "sending"), "sending");
  assert.equal(transitionProductionSubmission("sending", "received"), "received");
  assert.equal(transitionProductionSubmission("received", "processing"), "processing");
  assert.equal(
    transitionProductionSubmission("processing", "accepted", { finalAuthorityDecision: true }),
    "accepted",
  );
  assert.throws(() => transitionProductionSubmission("approved", "accepted", { finalAuthorityDecision: true }), /illegal/i);
  assert.throws(() => transitionProductionSubmission("accepted", "sending"), /terminal/i);
});

test("transport acknowledgement cannot become accepted", () => {
  assert.throws(
    () => transitionProductionSubmission("processing", "accepted", { finalAuthorityDecision: false }),
    /final authority decision/i,
  );
  assert.equal(
    classifyRf1086TransportOutcome({
      forsendelseId: "forsendelse-id",
      documents: ["<submitted-document />"],
      finalAuthorityDecision: null,
    }),
    "processing",
  );
});

test("uses explicit authority feedback for terminal outcomes", () => {
  assert.equal(classifyRf1086TransportOutcome({ forsendelseId: "id", documents: [], finalAuthorityDecision: "accepted" }), "accepted");
  assert.equal(classifyRf1086TransportOutcome({ forsendelseId: "id", documents: [], finalAuthorityDecision: "rejected" }), "rejected");
  assert.equal(classifyRf1086TransportOutcome({ forsendelseId: null, documents: [], finalAuthorityDecision: null }), "unknown");
});
