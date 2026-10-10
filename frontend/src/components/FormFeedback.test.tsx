import { expect, it } from "vitest";
import { ApiError } from "../api/client";
import { apiFieldIssues } from "./FormFeedback";

it("keeps nested server field paths and messages without guessing ownership", () => {
  const error = new ApiError(400, "invalid", "输入无效", {
    document: { rarities: [{ base_probability: ["概率总和必须为100%。"] }] },
    parameters: { seed: ["超出安全整数范围。"] },
  } as unknown as Record<string, string[]>);
  expect(apiFieldIssues(error)).toEqual({
    "document.rarities.0.base_probability": "概率总和必须为100%。",
    "parameters.seed": "超出安全整数范围。",
  });
});
