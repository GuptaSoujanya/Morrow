import { test } from "node:test";
import assert from "node:assert/strict";

test("planted failure", () => {
  assert.equal(1 + 1, 3);
});
