import React from "react";

export default function TradeLog({ trades }) {
  return (
    <div className="bg-gray-900 border border-gray-700 rounded p-4 flex-1">
      <div className="text-gray-400 text-xs font-bold uppercase tracking-wider mb-3">
        Trade Log
      </div>
      <div className="overflow-auto max-h-56 scrollbar-dark">
        <table className="w-full text-xs">
          <thead>
            <tr className="text-gray-500 border-b border-gray-700 sticky top-0 bg-gray-900">
              <th className="text-left pb-2">Time</th>
              <th className="text-left pb-2">Side</th>
              <th className="text-right pb-2">Price</th>
              <th className="text-right pb-2">P&amp;L</th>
              <th className="text-left pb-2">Exit</th>
              <th className="text-right pb-2">PV</th>
            </tr>
          </thead>
          <tbody>
            {(!trades || trades.length === 0) && (
              <tr>
                <td colSpan={6} className="text-center py-6 text-gray-600">
                  No trades yet
                </td>
              </tr>
            )}
            {(trades || []).slice(0, 50).map((t, i) => (
              <tr key={i} className="border-b border-gray-800">
                <td className="py-1.5 text-gray-400 whitespace-nowrap">
                  {(t.timestamp || "").slice(0, 16)}
                </td>
                <td className={`py-1.5 font-bold ${
                  t.side === "BUY" ? "text-green-400" : "text-red-400"
                }`}>
                  {t.side}
                </td>
                <td className="text-right py-1.5 text-white">{t.price?.toFixed(2)}</td>
                <td className={`text-right py-1.5 font-bold ${
                  (t.pnl || 0) >= 0 ? "text-green-400" : "text-red-400"
                }`}>
                  {(t.pnl || 0) >= 0 ? "+" : ""}{(t.pnl || 0).toFixed(2)}
                </td>
                <td className="py-1.5 text-gray-500">{t.exit_reason || "—"}</td>
                <td className="text-right py-1.5 text-gray-300">
                  {(t.portfolio_value || 0).toFixed(0)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
