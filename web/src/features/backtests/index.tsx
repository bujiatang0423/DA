export function BacktestsPage(): JSX.Element {
  return <section><h2>历史回测</h2><p>使用点时数据运行 V2.12 walk-forward 回测。</p></section>;
}

export const backtestsFeature = {
  id: "backtests", path: "/backtests", label: "历史回测", element: <BacktestsPage />,
} as const;
