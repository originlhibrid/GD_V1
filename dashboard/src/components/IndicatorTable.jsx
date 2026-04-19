import React from "react";

export default function IndicatorTable({ indicators }) {
  if (!indicators) {
    return (
      <div className="bg-gray-900 border border-gray-700 rounded p-4">
        <div className="text-gray-400 text-xs font-bold uppercase mb-3">Indicators</div>
        <div className="text-gray-600 text-xs text-center py-4">Loading...</div>
      </div>
    );
  }

  const bull = (v, t = 0) => v > t ? "text-green-400" : "text-red-400";
  const bear = (v, t = 0) => v < t ? "text-red-400" : "text-green-400";

  const rows = [
    { label: "ROC Fast",  key: "roc_fast",     fmt: (v) => v?.toFixed(3) ?? "—", colorFn: (v) => bull(v, 0)  },
    { label: "ROC Slow",  key: "roc_slow",     fmt: (v) => v?.toFixed(3) ?? "—", colorFn: (v) => bull(v, 0)  },
    { label: "Trend EMA",key: "trend_ema",     fmt: (v) => v?.toFixed(2) ?? "—", colorFn: () => "text-blue-400" },
    { label: "ATR",       key: "atr",          fmt: (v) => v?.toFixed(3) ?? "—", colorFn: () => "text-purple-400" },
    { label: "Mom Decay", key: "mom_decay",     fmt: (v) => v?.toFixed(3) ?? "—", colorFn: (v) => bear(v, 0)  },
  ];

  return (
    <div className="bg-gray-900 border border-gray-700 rounded p-4">
      <div className="text-gray-400 text-xs font-bold uppercase tracking-wider mb-3">Indicators</div>
      <table className="w-full text-xs">
        <tbody>
          {rows.map(({ label, key, fmt, colorFn }) => (
            <tr key={key} className="border-b border-gray-800 last:border-0">
              <td className="py-1.5 text-gray-500">{label}</td>
              <td className={`text-right py-1.5 font-bold ${colorFn(indicators[key])}`}>
                {fmt(indicators[key])}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
