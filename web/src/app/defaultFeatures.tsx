import {runsFeature} from "../features/runs";
import {candidatesFeature} from "../features/candidates";
import {holdingsFeature} from "../features/holdings";
import {maintenanceFeature} from "../features/portfolio/MaintenancePage";
import {backtestsFeature} from "../features/backtests";
import {legacyImportFeature} from "../features/legacyImport";

export const defaultFeatures = [candidatesFeature, holdingsFeature, maintenanceFeature, backtestsFeature, legacyImportFeature, runsFeature] as const;
