import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import type { FeatureDefinition } from "../../app/featureRegistry";
import { HoldingAnalysisPage } from "./HoldingAnalysisPage";

const holdingQueryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
});

export { HoldingAnalysisPage };
export const HoldingsPage = HoldingAnalysisPage;

export const holdingsFeature: FeatureDefinition = {
    id: "holdings",
    path: "/holdings",
    label: "持仓分析",
    element: (
        <QueryClientProvider client={holdingQueryClient}>
            <HoldingAnalysisPage />
        </QueryClientProvider>
    ),
};

export const holdingFeature = holdingsFeature;
