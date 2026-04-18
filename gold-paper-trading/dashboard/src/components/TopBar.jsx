import React from "react";

export default function TopBar({
  asset, price, connected, lastBarTime,
  timeframe, inPos, pv, tradeCount, winRate,
}) {
  const fmt = (n) => typeof n === "number" ? n.toFixed(2) : "—";
  const fmtK = (n) => typeof n === "number" ? n.toLocaleString(undefined, {minimumFractionDigits: 0}) : "—";
  const ret = pv > 0 ? ((pv - 10000) / 10000) * 100 : 0;

  return (
    <div className="bg-gray-900 border border-gray-700 rounded px-4 py-2 flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-4">
        <span className="text-yellow-400 font-bold text-lg tracking-widest">{asset}</span>
        <div className="flex items-center gap-2">
          <span className="text-white text-xl font-bold">{fmt(price)}</span>
          <span className={`text-sm font-bold ${ret >= 0 ? "text-green-400" : "text-red-400"}`}>
            {ret >= 0 ? "+" : ""}{ret.toFixed(2)}%
          </span>
        </div>
      </div>

      <div className="flex items-center gap-4">
        {/* TF badge */}
        <span className="bg-gray-800 text-yellow-400 px-3 py-1 rounded text-xs font-bold uppercase">
          {timeframe}
        </span>

        {/* Stats for this instance */}
        <div className="hidden md:flex items-center gap-3 text-xs">
          <div className="text-gray-400">
            PV: <span className="text-white font-bold">{fmtK(pv)}</span>
          </div>
          <div className="text-gray-400">
            Trades: <span className="text-white">{tradeCount}</span>
          </div>
          <div className="text-gray-400">
            Win: <span className="text-white">{winRate.toFixed(0)}%</span>
          </div>
        </div>

        {/* Connection */}
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${connected ? "bg-green-400" : "bg-red-500"}`} />
          <span className="text-xs text-gray-400">{connected ? "LIVE" : "RECONNECT"}</span>
        </div>

        {lastBarTime && (
          <span className="text-xs text-gray-500 hidden lg:block">{lastBarTime}</span>
        )}
      </div>
    </div>
  );
}
