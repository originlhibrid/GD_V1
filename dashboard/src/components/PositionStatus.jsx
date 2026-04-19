import React from "react";

const MOM_THRESH = 2.5;

export default function PositionStatus({ tick, status, entry, trail }) {
  // Prefer live tick data, fall back to status snapshot
  const price = tick?.latest_price || status?.latest_price || 0;
  const inPos = tick?.in_position ?? status?.in_position ?? false;
  const peak  = tick?.peak_price   || status?.peak_price   || 0;
  const pv    = tick?.portfolio_value || status?.portfolio_value || 10000;
  const cash  = tick?.cash         || status?.cash          || pv;
  const momStr = Math.abs(tick?.momentum_strength || status?.momentum_strength || 0);
  const rocFast = tick?.roc_fast || status?.roc_fast || 0;
  const rocSlow = tick?.roc_slow || status?.roc_slow || 0;
  const momDecay = tick?.mom_decay || status?.mom_decay || 0;

  const posVal = inPos ? pv - cash : 0;
  const unrealPnl = inPos && entry > 0 ? posVal * (price - entry) / entry : 0;
  const pnlPct   = inPos && entry > 0 ? ((price - entry) / entry) * 100 : 0;
  const trailDist = inPos && trail > 0 ? ((price - trail) / price) * 100 : 0;

  const fmt  = (n) => typeof n === "number" ? n.toFixed(2) : "—";
  const fmtP = (n) => (n >= 0 ? "+" : "") + (typeof n === "number" ? n.toFixed(2) : "—");

  return (
    <div className="bg-gray-900 border border-gray-700 rounded p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-gray-400 text-xs font-bold uppercase tracking-wider">Position</span>
        <div className={`px-3 py-1 rounded font-bold text-sm ${
          inPos ? "bg-green-900 text-green-400" : "bg-gray-700 text-gray-400"
        }`}>
          {inPos ? "IN POSITION" : "OUT OF MARKET"}
        </div>
      </div>

      <div className="space-y-2 text-sm">
        <div className="flex justify-between">
          <span className="text-gray-500">Entry</span>
          <span className="text-white">{entry > 0 ? `$${fmt(entry)}` : "—"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Current</span>
          <span className="text-yellow-400 font-bold">{price > 0 ? `$${fmt(price)}` : "—"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-gray-500">Peak</span>
          <span className="text-white">{peak > 0 ? `$${fmt(peak)}` : "—"}</span>
        </div>

        {inPos && (
          <>
            <div className="flex justify-between">
              <span className="text-gray-500">Unreal. P&amp;L</span>
              <span className={unrealPnl >= 0 ? "text-green-400" : "text-red-400"}>
                {fmtP(unrealPnl)} ({fmtP(pnlPct)}%)
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Trail Stop</span>
              <span className="text-orange-400">{trail > 0 ? `$${fmt(trail)}` : "—"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-500">Trail Dist.</span>
              <span className="text-gray-300">{trailDist.toFixed(2)}%</span>
            </div>
          </>
        )}

        {/* Momentum strength bar */}
        <div>
          <div className="flex justify-between mb-1">
            <span className="text-gray-500 text-xs">Momentum</span>
            <span className="text-gray-300 text-xs">
              {momStr.toFixed(2)} / {MOM_THRESH}
            </span>
          </div>
          <div className="w-full bg-gray-700 rounded h-2">
            <div
              className={`h-2 rounded transition-all ${
                momStr > MOM_THRESH ? "bg-green-500" : "bg-yellow-500"
              }`}
              style={{ width: `${Math.min((momStr / (MOM_THRESH * 2)) * 100, 100)}%` }}
            />
          </div>
        </div>

        {/* Quick indicator readout */}
        <div className="grid grid-cols-3 gap-1 text-xs pt-1">
          <div className="text-center">
            <div className="text-gray-500">ROC F</div>
            <div className={rocFast > 0 ? "text-green-400" : "text-red-400"}>
              {rocFast.toFixed(2)}
            </div>
          </div>
          <div className="text-center">
            <div className="text-gray-500">ROC S</div>
            <div className={rocSlow > 0 ? "text-green-400" : "text-red-400"}>
              {rocSlow.toFixed(2)}
            </div>
          </div>
          <div className="text-center">
            <div className="text-gray-500">MomDec</div>
            <div className={momDecay >= 0 ? "text-green-400" : "text-red-400"}>
              {momDecay.toFixed(2)}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
