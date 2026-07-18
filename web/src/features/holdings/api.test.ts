import { afterEach, expect, test, vi } from "vitest";

import { holdingApi } from "./api";

afterEach(() => vi.unstubAllGlobals());

test("maps a missing latest analysis to an empty result for the requested portfolio", async () => {
  const fetchMock = vi
    .fn()
    .mockResolvedValue(new Response(null, { status: 404 }));
  vi.stubGlobal("fetch", fetchMock);

  await expect(holdingApi.latest("family-account")).resolves.toBeNull();
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/v1/holding-analyses/latest?portfolio_id=family-account",
    undefined,
  );
});
