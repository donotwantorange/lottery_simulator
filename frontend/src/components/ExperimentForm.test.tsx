import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExperimentForm, initialParameters, validateParameters } from "./ExperimentForm";

describe("ExperimentForm", () => {
  it("keeps a very large seed as decimal text and rejects zero", () => {
    let value = { ...initialParameters };
    render(<ExperimentForm value={value} onChange={(next) => { value = next; }} />);
    const seed = "900719925474099312345678901234567890";
    fireEvent.change(screen.getByLabelText("随机种子（可留空，由系统生成）"), { target: { value: seed } });
    expect(value.seed).toBe(seed);
    expect(validateParameters(value)).toBeNull();
    expect(validateParameters({ ...value, seed: "0" })).toContain("不能为0");
  });
});
