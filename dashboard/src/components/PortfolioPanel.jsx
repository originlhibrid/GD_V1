import React, { useEffect, useRef } from "react";
import { createChart } from "lightweight-charts";

const START = 10000;

export default function PortfolioPanel({ equity, trades, params, pv }) {
  const chartRef = useRef(null);
  const chartInst = useRef(null);

  const ret = pv > 0 ? ((pv - START) / START) * 100 : 0;
  const winRate = trades.length > 0
    ? (trades.filter((t) => t.pnl > 0).length / trades.length) * 100
    : 0;

  const wins = trades.filter((t) => t.pnl > 0).reduce((s, t) => s + t.pnl, 0);
  const losses = Math.abs(trades.filter((t) => t.pnl < 0).reduce((s, t) => s + t.pnl, 0));
  const profitFactor = losses > 0 ? (wins / losses) : wins > 0 ? Infinity : 0;

  const maxDD = (() => {
    if (equity.length === 0) return 0;
    let peak = START;
    let maxD = 0;
    for (const e of equity) {
      if (e.portfolio_value > peak) peak = e.portfolio_value;
      const dd = ((e.portfolio_value - peak) / peak) * 100;
      if (dd < maxD) maxD = dd;
    }
    return maxD;
  })();

  useEffect(() => {
    if (!chartRef.current) return;
    if (chartInst.current) { chartInst.current.remove(); chartInst.current = null; }
    if (equity.length === 0) return;

    const chart = createChart(chartRef.current, {
      layout: { background: { color: "#0f1117" }, textColor: "#9ca3af" },
      grid: { vertLines: { color: "#1f2937" }, horzLines: { color: "#1f2937" } },
      rightPriceScale: { borderColor: "#374151" },
      timeScale: { borderColor: "#374151" },
      height: 160,
    });
    const line = chart.addLineSeries({ color: "#22c55e", lineWidth: 2 });
    line.setData(
      equity.map((e) => ({
        time: (e.timestamp || "").replace(" ", "T") + "Z",
        value: e.portfolio_value,
      }))
    );
    chart.timeScale().fitContent();
    chartInst.current = chart;

    const ro = () => chart.applyOptions({ width: chartRef.current.clientWidth });
    window.addEventListener("resize", ro);
    return () => { window.removeEventListener("resize", ro); chart.remove(); };
  }, [equity.length]);

  const pfLabel = profitFactor === Infinity ? "∞" : profitFactor.toFixed(2);

  return (
    <div className="bg-gray-900 border border-gray-700 rounded p-4">
      <div className="text-gray-400 text-xs font-bold uppercase tracking-wider mb-3">
        Portfolio — {params.timeframe || "5m"}
      </div>

      <div className="flex justify-between items-end mb-2">
        <div>
          <div className="text-gray-500 text-xs">Starting</div>
          <div className="text-white">${START.toLocaleString()}</div>
        </div>
        <div className="text-right">
          <div className="text-gray-500 text-xs">Current</div>
          <div className={`text-xl font-bold ${ret >= 0 ? "text-green-400" : "text-red-400"}`}>
            ${pv > 0 ? pv.toLocaleString(undefined, { minimumFractionDigits: 2 }) : "—"}
          </div>
        </div>
      </div>

      <div className={`text-center text-lg font-bold mb-2 ${ret >= 0 ? "text-green-400" : "text-red-400"}`}>
        {ret >= 0 ? "+" : ""}{ret.toFixed(2)}%
      </div>

      <div ref={chartRef} className="w-full mb-2" />

      <div className="grid grid-cols-4 gap-1 text-xs">
        {[
          { label: "Max DD", val: `${maxDD.toFixed(1)}%`, color: "text-red-400" },
          { label: "Trades", val: trades.length, color: "text-white" },
          { label: "Win %", val: `${winRate.toFixed(0)}%`, color: "text-white" },
          { label: "PF", val: pfLabel, color: "text-blue-400" },
        ].map(({ label, val, color }) => (
          <div key={label} className="bg-gray-800 rounded p-1.5 text-center">
            <div className="text-gray-500 text-xs">{label}</div>
            <div className={`font-bold ${color}`}>{val}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
