import { expect, test } from "@playwright/test";

test("candidate, holding, backtest and run center expose persisted local jobs", async ({ page }) => {
  await page.goto("/");

  await page.getByRole("link", { name: "候选推荐" }).click();
  await page.getByRole("button", { name: "生成候选" }).click();
  await expect(page.getByText("金融风险信号")).toBeVisible();
  await expect(page.getByText("仅供人工确认，不自动下单")).toBeVisible();

  await page.getByRole("link", { name: "持仓分析" }).click();
  await expect(page.getByRole("heading", { name: "持仓分析" })).toBeVisible();
  await page.getByRole("button", { name: "分析当前持仓" }).click();
  await expect(page.getByRole("link", { name: "查看运行进度" })).toBeVisible();

  await page.getByRole("link", { name: "历史回测" }).click();
  await page.getByRole("button", { name: "开始回测" }).click();
  await expect(page.getByText("研究级数据", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "权益曲线审计" })).toBeVisible();

  await page.getByRole("link", { name: "运行中心" }).click();
  await expect(page.getByText("candidate_recommendation · succeeded")).toBeVisible();
  await expect(page.getByText("holding_analysis · succeeded")).toBeVisible();
  await expect(page.getByText("backtest · succeeded")).toBeVisible();
});
