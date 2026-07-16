import {runsFeature} from "../features/runs";
import {candidatesFeature} from "../features/candidates";
import {holdingsFeature} from "../features/holdings";
import {backtestsFeature} from "../features/backtests";

export const defaultFeatures = [candidatesFeature, holdingsFeature, backtestsFeature, runsFeature] as const;
