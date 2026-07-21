import { expect, test } from "@playwright/test";

test("candidate, holding, backtest and run center expose persisted local jobs", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("link", { name: "候选推荐" }).click();
  await page.getByRole("button", { name: "生成候选" }).click();
  await expect(page.getByText("研究级数据，不代表正式历史验证")).toBeVisible();
  await expect(page.getByRole("heading", { name: "可执行" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "观察" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "排除" })).toBeVisible();

  await page.getByRole("link", { name: "持仓分析" }).click();
  await expect(page.getByRole("heading", { name: "持仓分析" })).toBeVisible();
  await page.getByRole("button", { name: "分析当前持仓" }).click();
  await expect(page.getByRole("link", { name: "查看运行进度" })).toBeVisible();

  await page.getByRole("link", { name: "历史回测" }).click();
  await page.locator('input[type="date"]').nth(0).fill("2020-06-01");
  await page.locator('input[type="date"]').nth(1).fill("2020-06-02");
  await page.getByRole("button", { name: "开始回测" }).click();
  await expect(page.getByText("权益曲线审计")).toBeVisible();

  await page.getByRole("link", { name: "运行中心" }).click();
  await expect(page.getByText("candidate_recommendation · succeeded")).toBeVisible();
  await expect(page.getByText("holding_analysis · succeeded")).toBeVisible();
  await expect(page.getByText("backtest · succeeded")).toBeVisible();
});
