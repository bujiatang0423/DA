export function HoldingsPage(): JSX.Element {
  return <section><h2>持仓分析</h2><p>查看持仓敞口、回撤与止损状态。</p></section>;
}

export const holdingsFeature = {
  id: "holdings", path: "/holdings", label: "持仓分析", element: <HoldingsPage />,
} as const;
