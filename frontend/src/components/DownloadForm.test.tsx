import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { DownloadForm } from "./DownloadForm";

const { currentCsrfToken } = vi.hoisted(() => ({ currentCsrfToken: vi.fn() }));
vi.mock("../api/client", () => ({ currentCsrfToken, errorMessage: () => "无法获取令牌" }));

afterEach(() => { cleanup(); vi.restoreAllMocks(); currentCsrfToken.mockReset(); });

it("opens the download tab during the click and submits a native CSRF form", async () => {
  let release!: (value: string) => void;
  currentCsrfToken.mockReturnValue(new Promise<string>((resolve) => { release = resolve; }));
  const opened = { close: vi.fn() };
  const popup = vi.spyOn(window, "open").mockReturnValue(opened as unknown as Window);
  const submit = vi.spyOn(HTMLFormElement.prototype, "submit").mockImplementation(() => undefined);
  render(<DownloadForm runId="run-1" filters={{ rarity: 6, source: "main" }} matchingTotal="3" limit="10" />);
  expect(screen.getByText(/下载当前筛选结果：3 条；当前账号适用限额：10 条/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /下载当前筛选结果/ }));
  expect(popup).toHaveBeenCalledOnce();
  expect(submit).not.toHaveBeenCalled();
  release("csrf-current");
  await waitFor(() => expect(submit).toHaveBeenCalledOnce());
  const form = screen.getByRole("button", { name: /下载当前筛选结果/ }).closest("form")!;
  expect(form.method).toBe("post");
  expect(form.target).toMatch(/^trace-download-/);
  expect((form.elements.namedItem("csrfmiddlewaretoken") as HTMLInputElement).value).toBe("csrf-current");
  expect((form.elements.namedItem("filters") as HTMLInputElement).value).toBe('{"rarity":6,"source":"main"}');
});

it("uses the matching total for the download limit rather than the current page size", () => {
  render(<DownloadForm runId="run-1" filters={{ trial_from: "1" }} matchingTotal="10001" limit="10000" />);
  expect(screen.getByRole("button", { name: /下载当前筛选结果/ })).toBeDisabled();
  expect(screen.getByText(/超过适用下载限额/)).toBeInTheDocument();
});
