import React from "react";

const KEYS = [
  ["roc_fast_period",        "ROC Fast"],
  ["roc_slow_period",        "ROC Slow"],
  ["trend_period",           "Trend EMA"],
  ["atr_period",             "ATR"],
  ["base_trailing_atr_mult", "Trail Mult"],
  ["trail_tighten_mult",     "Tighten"],
  ["mom_strong_threshold",   "Mom Thresh"],
  ["mom_decay_period",       "Mom Decay"],
  ["wait_buy",               "Wait Buy"],
  ["wait_sell",              "Wait Sell"],
];

export default function ParamsPanel({ params }) {
  return (
    <div className="bg-gray-900 border border-gray-700 rounded p-4">
      <div className="flex items-center justify-between mb-3">
        <span className="text-gray-400 text-xs font-bold uppercase tracking-wider">
          Strategy
        </span>
        <span className="bg-yellow-600 text-black text-xs px-2 py-0.5 rounded font-bold">
          momentum_adaptive_v7
        </span>
      </div>
      <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-xs">
        {KEYS.map(([k, label]) => (
          <React.Fragment key={k}>
            <span className="text-gray-500">{label}</span>
            <span className="text-white text-right font-mono">
              {params[k] != null ? String(params[k]) : "—"}
            </span>
          </React.Fragment>
        ))}
      </div>
      {params.timeframe && (
        <div className="mt-2 pt-2 border-t border-gray-800 flex justify-between text-xs">
          <span className="text-gray-500">Instance</span>
          <span className="text-yellow-400 font-bold uppercase">{params.timeframe}</span>
        </div>
      )}
    </div>
  );
}
