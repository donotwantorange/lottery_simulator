import { describe, expect, it } from "vitest";
import {
  eventTypeLabel,
  formatCount,
  formatProbability,
  formatQuantity,
  jobStageLabel,
  jobStatusLabel,
  mechanismLabel,
  sourceLabel,
} from "./formatters";

describe("formatCount", () => {
  it("groups large integer strings without losing digits", () => {
    expect(formatCount("9007199254740993123456789")).toBe("9,007,199,254,740,993,123,456,789");
    expect(formatCount(1234567n)).toBe("1,234,567");
  });

  it("keeps zero distinct from missing and formats decimal values", () => {
    expect(formatCount(0)).toBe("0");
    expect(formatCount(null)).toBe("数据缺失");
    expect(formatCount(undefined)).toBe("数据缺失");
    expect(formatCount("-12345.60")).toBe("-12,345.60");
  });
});

describe("formatProbability", () => {
  it("formats percentages and keeps tiny positive values from looking like zero", () => {
    expect(formatProbability(0.125)).toBe("12.5%");
    expect(formatProbability(0)).toBe("0%");
    expect(formatProbability(1e-12)).toMatch(/[1-9].*e-\d+%/i);
  });

  it("labels missing and invalid probabilities explicitly", () => {
    expect(formatProbability(null)).toBe("数据缺失");
    expect(formatProbability(undefined)).toBe("数据缺失");
    expect(formatProbability(Number.NaN)).toBe("数据无效");
  });
});

describe("formatQuantity", () => {
  it("formats finite reward quantities while preserving zero and missingness", () => {
    expect(formatQuantity(12000)).toBe("12,000");
    expect(formatQuantity(0)).toBe("0");
    expect(formatQuantity(null)).toBe("数据缺失");
    expect(formatQuantity(undefined)).toBe("数据缺失");
    expect(formatQuantity(Number.POSITIVE_INFINITY)).toBe("数据无效");
  });
});

describe("trace and job labels", () => {
  it("translates actual job statuses and phases and identifies unknown values", () => {
    expect(jobStatusLabel("queued")).toBe("排队中");
    expect(jobStatusLabel("completed")).toBe("已完成");
    expect(jobStatusLabel("mystery")).toBe("未知状态（mystery）");
    expect(jobStageLabel("simulating")).toBe("正在模拟");
    expect(jobStageLabel("committing")).toBe("正在提交结果");
    expect(jobStageLabel("mystery")).toBe("未知阶段（mystery）");
  });

  it("translates actual trace event, source, and mechanism values only", () => {
    expect(eventTypeLabel("draw")).toBe("抽取");
    expect(eventTypeLabel("character_grant")).toBe("角色赠送");
    expect(sourceLabel("main")).toBe("主池");
    expect(sourceLabel("bonus")).toBe("赠送池抽取");
    expect(mechanismLabel("first_bonus")).toBe("首次赠送抽取");
    expect(mechanismLabel("periodic_grant")).toBe("周期直接赠送");
    expect(mechanismLabel("future_mechanism")).toBe("未知机制（future_mechanism）");
    expect(mechanismLabel(null)).toBe("数据缺失");
  });
});
