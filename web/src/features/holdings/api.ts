import type { components } from "../../generated/schema";
import { ApiError, apiClient } from "../../shared/api/client";

export type HoldingRequest =
  components["schemas"]["backend__app__features__holdings__contracts__HoldingAnalysisRequest"];
export type HoldingResult =
  components["schemas"]["backend__app__features__holdings__contracts__HoldingAnalysisResponse"];
export type PositionPage = components["schemas"]["PortfolioPositionPage"];
export type PositionCorrection =
  components["schemas"]["PositionCorrectionRequest"];
export type ManualFill = components["schemas"]["ManualFillRequest"];
export type RunRef = components["schemas"]["RunRef"];

function queryForPortfolio(portfolioId: string): string {
  return `?portfolio_id=${encodeURIComponent(portfolioId)}`;
}

export const holdingApi = {
  positions: (portfolioId: string): Promise<PositionPage> =>
    apiClient.get<PositionPage>(
      `/api/v1/portfolio/positions${queryForPortfolio(portfolioId)}`,
    ),
  correctPositions: (request: PositionCorrection): Promise<PositionPage> =>
    apiClient.put<PositionPage, PositionCorrection>(
      "/api/v1/portfolio/positions",
      request,
    ),
  recordManualFill: (request: ManualFill): Promise<PositionPage> =>
    apiClient.post<PositionPage, ManualFill>(
      "/api/v1/portfolio/fills",
      request,
    ),
  latest: async (portfolioId: string): Promise<HoldingResult | null> => {
    try {
      return await apiClient.get<HoldingResult>(
        `/api/v1/holding-analyses/latest${queryForPortfolio(portfolioId)}`,
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        return null;
      }
      throw error;
    }
  },
  submit: (request: HoldingRequest, idempotencyKey: string): Promise<RunRef> =>
    apiClient.post<RunRef, HoldingRequest>(
      "/api/v1/holding-analyses",
      request,
      {
        "Idempotency-Key": idempotencyKey,
      },
    ),
};
