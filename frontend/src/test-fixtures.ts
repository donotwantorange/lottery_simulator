import defaultRule from "../../configs/rules/zmd.json";
import defaultPool from "../../configs/pools/default.json";
import defaultExperiment from "../../configs/experiments/default.json";
import type { ExperimentParameters, PoolDocument, RuleDocument } from "./api/types";

export function makeRuleDocument(): RuleDocument {
  return structuredClone(defaultRule) as RuleDocument;
}

export function makePoolDocument(): PoolDocument {
  return structuredClone(defaultPool) as PoolDocument;
}

export function makeExperimentParameters(): ExperimentParameters {
  const parameters = structuredClone(defaultExperiment.parameters);
  return {
    ...parameters,
    draws: String(parameters.draws),
    trials: String(parameters.trials),
    seed: parameters.seed === null ? null : String(parameters.seed),
    initial_main_draws: String(parameters.initial_main_draws),
    initial_small_pity: Object.fromEntries(
      Object.entries(parameters.initial_small_pity).map(([id, value]) => [id, String(value)]),
    ),
    initial_big_pity: { ...parameters.initial_big_pity, misses: String(parameters.initial_big_pity.misses) },
  };
}
