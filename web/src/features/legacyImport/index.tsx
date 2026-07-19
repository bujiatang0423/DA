import type { FeatureDefinition } from "../../app/featureRegistry";
import { LegacyImportPage } from "./LegacyImportPage";

export const legacyImportFeature: FeatureDefinition = {
  id: "legacy-import",
  path: "/legacy-imports",
  label: "历史导入",
  element: <LegacyImportPage />,
};

export { LegacyImportPage };
