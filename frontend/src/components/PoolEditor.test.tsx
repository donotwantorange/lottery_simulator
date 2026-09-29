import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import defaultPool from "../../../configs/pools/default.json";
import type { PoolDocument } from "../api/types";
import { PoolEditor } from "./PoolEditor";

describe("PoolEditor", () => {
  it("edits roster membership, UP weight, and reward values in the pool document", () => {
    let value = structuredClone(defaultPool) as PoolDocument;
    const renderEditor = () => <PoolEditor value={value} kind="private" visibility="hidden" canCreatePublic={false}
      editing={false} onChange={(next) => { value = next; rerender(renderEditor()); }} onKind={() => undefined} onVisibility={() => undefined} />;
    const { rerender } = render(renderEditor());
    const up = screen.getByLabelText("六星角色1 UP");
    fireEvent.click(up);
    expect(value.pool_config.six_star_characters[0].is_up).toBe(false);
    fireEvent.click(screen.getByLabelText("六星角色1 UP"));
    expect(value.pool_config.six_star_characters[0].is_up).toBe(true);
    expect(value.pool_config.six_star_characters[0].up_weight).toBe(1);
    const probability = screen.getByLabelText("UP占六星概率");
    fireEvent.change(probability, { target: { value: "0." } });
    expect(probability).toHaveValue("0.");
    expect(value.pool_config.up_share).toBe(0.5);
    fireEvent.change(probability, { target: { value: "0.7" } });
    fireEvent.blur(probability);
    expect(value.pool_config.up_share).toBe(0.7);
    const reward = screen.getByLabelText("奖励1six_star数值");
    fireEvent.change(reward, { target: { value: "37" } });
    fireEvent.blur(reward);
    expect(value.pool_config.rewards[0].six_star).toBe(37);
    expect(screen.getByText("附赠奖励")).toBeTruthy();
  });
});
