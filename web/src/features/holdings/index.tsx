import type { FeatureDefinition } from "../../app/featureRegistry";
import { HoldingAnalysisPage } from "./HoldingAnalysisPage";

export { HoldingAnalysisPage };
export const HoldingsPage = HoldingAnalysisPage;

export const holdingsFeature: FeatureDefinition = {
  id: "holdings",
  path: "/holdings",
  label: "持仓分析",
  element: <HoldingAnalysisPage />,
};
