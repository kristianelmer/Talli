import assert from "node:assert/strict";
import test from "node:test";

import {
  assertSystemUserTransition,
  generateSystemUserExternalRef,
} from "../app/lib/system-user-requests.ts";

test("external references are opaque and transitions are monotonic", () => {
  const reference = generateSystemUserExternalRef();

  assert.match(reference, /^[A-Za-z0-9_-]{43}$/u);
  assert.doesNotMatch(reference, /930835978|@|\s/u);
  assert.equal(assertSystemUserTransition("creating", "new"), "new");
  assert.equal(assertSystemUserTransition("new", "accepted"), "accepted");
  assert.throws(
    () => assertSystemUserTransition("accepted", "new"),
    /invalid_system_user_transition/u,
  );
});

test("terminal Altinn failures cannot be reopened", () => {
  for (const status of ["rejected", "denied", "timedout"]) {
    assert.throws(
      () => assertSystemUserTransition(status, "new"),
      /invalid_system_user_transition/u,
    );
  }
});

test("invalid runtime statuses use the stable transition error", () => {
  for (const [from, to] of [["unknown", "new"], ["new", "unknown"]]) {
    assert.throws(
      () => assertSystemUserTransition(from, to),
      (error) => error instanceof Error && error.message === "invalid_system_user_transition",
    );
  }
});
