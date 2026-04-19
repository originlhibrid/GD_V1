import { useState, useEffect, useRef } from "react";

const KRONOS_COLORS = {
  bullish: { border: "border-green-500", badge: "🟢 BULLISH",  bar: "bg-green-500" },
  bearish: { border: "border-red-500",   badge: "🔴 BEARISH",  bar: "bg-red-500"   },
  neutral: { border: "border-gray-500",  badge: "⚪️ NEUTRAL",  bar: "bg-gray-400"  },
};

const VOL_LABELS = { true: "HIGH", false: "NORMAL" };
const ACTION_LABELS = {
  none:    "NONE",
  confirm: "CONFIRM",
  tighten: "TIGHTEN",
  block:   "BLOCK",
};

export default function KronosPanel({ kronosData, stats }) {
  const [pulse, setPulse] = useState(false);
  const prevDirRef = useRef(null);

  const dir     = kronosData?.direction || "neutral";
  const conf    = kronosData?.confidence || 0;
  const pred    = kronosData?.predicted_close || 0;
  const volHigh = kronosData?.volatility_high ?? null;
  const action  = kronosData?.action || "none";

  const offline = kronosData === null || kronosData === undefined;

  // Pulse animation on direction change
  useEffect(() => {
    if (prevDirRef.current !== null && prevDirRef.current !== dir) {
      setPulse(true);
      const t = setTimeout(() => setPulse(false), 1000);
      return () => clearTimeout(t);
    }
    prevDirRef.current = dir;
  }, [dir]);

  const colors  = KRONOS_COLORS[dir] || KRONOS_COLORS.neutral;
  const confPct = Math.round(conf * 100);

  if (offline) {
    return (
      <div className="bg-gray-900 rounded-lg p-4 border border-gray-600">
        <div className="flex items-center gap-2 mb-3">
          <span className="text-xl">🤖</span>
          <span className="font-bold text-gray-300">KRONOS AI</span>
        </div>
        <div className="bg-gray-800 rounded p-4 text-center">
          <p className="text-yellow-400 text-sm font-semibold">⚠️ KRONOS OFFLINE</p>
          <p className="text-gray-500 text-xs mt-1">Model not loaded or engine not running</p>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`bg-gray-900 rounded-lg p-4 border-2 ${colors.border} ${pulse ? "animate-pulse" : ""}`}
    >
      {/* Header */}
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xl">🤖</span>
        <span className="font-bold text-gray-200">KRONOS AI</span>
        {pulse && <span className="text-xs text-yellow-400 ml-auto">NEW SIGNAL</span>}
      </div>

      {/* Signal block */}
      <div className="space-y-2 mb-3">
        <div className="flex justify-between text-sm">
          <span className="text-gray-400">Signal</span>
          <span className="font-bold text-white">{colors.badge}</span>
        </div>

        {/* Confidence bar */}
        <div>
          <div className="flex justify-between text-xs text-gray-400 mb-1">
            <span>Confidence</span>
            <span>{confPct}%</span>
          </div>
          <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
            <div
              className={`h-full ${colors.bar} transition-all duration-500`}
              style={{ width: `${confPct}%` }}
            />
          </div>
        </div>

        {/* Predicted close */}
        <div className="flex justify-between text-sm">
          <span className="text-gray-400">Pred Close</span>
          <span className="text-white font-mono">
            {pred > 0 ? `$${pred.toFixed(2)}` : "—"}
          </span>
        </div>

        {/* Volatility */}
        <div className="flex justify-between text-sm">
          <span className="text-gray-400">Volatility</span>
          <span className={volHigh ? "text-yellow-400 font-semibold" : "text-gray-300"}>
            {VOL_LABELS[volHigh] ?? "—"}
          </span>
        </div>

        {/* Action */}
        <div className="flex justify-between text-sm">
          <span className="text-gray-400">Action</span>
          <span className={`font-semibold ${
            action === "confirm" ? "text-green-400" :
            action === "tighten" ? "text-orange-400" :
            action === "block"   ? "text-red-400"   :
            "text-gray-400"
          }`}>
            {ACTION_LABELS[action] ?? action.toUpperCase()}
          </span>
        </div>
      </div>

      {/* Divider */}
      <div className="border-t border-gray-700 my-3" />

      {/* Stats */}
      <div className="grid grid-cols-3 gap-2 text-center">
        <div>
          <div className="text-xs text-gray-500">Overrides</div>
          <div className="text-white font-bold text-sm">{stats?.overrides ?? 0}</div>
        </div>
        <div>
          <div className="text-xs text-gray-500">Blocks</div>
          <div className="text-white font-bold text-sm">{stats?.blocks ?? 0}</div>
        </div>
        <div>
          <div className="text-xs text-gray-500">Confirms</div>
          <div className="text-white font-bold text-sm">{stats?.confirms ?? 0}</div>
        </div>
      </div>
    </div>
  );
}
