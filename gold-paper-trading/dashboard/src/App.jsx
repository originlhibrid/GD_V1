import { useState, useEffect, useCallback, useRef } from "react";
import TopBar from "./components/TopBar.jsx";
import MainChart from "./components/MainChart.jsx";
import PositionStatus from "./components/PositionStatus.jsx";
import PortfolioPanel from "./components/PortfolioPanel.jsx";
import IndicatorTable from "./components/IndicatorTable.jsx";
import TradeLog from "./components/TradeLog.jsx";
import ParamsPanel from "./components/ParamsPanel.jsx";
import { useWebSocket } from "./hooks/useWebSocket.js";

const API = import.meta.env.VITE_API_URL || `http://${window.location.host}`;
const TIMEFRAMES = ["5m", "15m", "1h"];
const STARTING_CAPITAL = 10000;

function useTfData(timeframe) {
  const [tick, setTick] = useState(null);
  const [status, setStatus] = useState(null);
  const [indicators, setIndicators] = useState(null);
  const [trades, setTrades] = useState([]);
  const [equity, setEquity] = useState([]);
  const [candles, setCandles] = useState([]);
  const [params, setParams] = useState({});
  const pollRef = useRef(null);

  const onTick = useCallback((data) => {
    if (data.timeframe === timeframe) setTick(data);
  }, [timeframe]);

  const { connected } = useWebSocket(onTick, timeframe);

  const fetchAll = useCallback(async () => {
    try {
      const tf = `?timeframe=${timeframe}`;
      const [s, ind, t, eq, p, c] = await Promise.all([
        fetch(`${API}/status${tf}`).then((r) => r.json()),
        fetch(`${API}/indicators${tf}`).then((r) => r.json()),
        fetch(`${API}/trades${tf}&limit=50`).then((r) => r.json()),
        fetch(`${API}/equity${tf}&hours=168`).then((r) => r.json()),
        fetch(`${API}/params${tf}`).then((r) => r.json()),
        fetch(`${API}/candles/${timeframe}?limit=200`).then((r) => r.json()),
      ]);
      setStatus(s);
      setIndicators(ind);
      setTrades(t);
      setEquity(eq);
      setParams(p);
      setCandles(Array.isArray(c) ? c : []);
    } catch (e) {
      console.error(`[${timeframe}] fetch error:`, e);
    }
  }, [timeframe]);

  // Polling fallback when WS is disconnected
  useEffect(() => {
    if (!connected) {
      pollRef.current = setInterval(fetchAll, 5000);
    } else {
      clearInterval(pollRef.current);
    }
    return () => clearInterval(pollRef.current);
  }, [connected, fetchAll]);

  // Initial load + refresh when tab changes
  useEffect(() => {
    setTick(null);
    setStatus(null);
    setIndicators(null);
    setTrades([]);
    setEquity([]);
    setCandles([]);
    setParams({});
    fetchAll();
    // Candles separately (different endpoint shape)
    fetch(`${API}/candles/${timeframe}?limit=200`)
      .then((r) => r.json())
      .then((c) => setCandles(Array.isArray(c) ? c : []))
      .catch(() => {});
  }, [timeframe, fetchAll]);

  const price = tick?.latest_price || status?.latest_price || 0;
  const inPos = tick?.in_position ?? status?.in_position ?? false;
  const pv = tick?.portfolio_value || status?.portfolio_value || STARTING_CAPITAL;
  const entry = tick?.entry_price || status?.entry_price || 0;
  const trail = tick?.trailing_stop || status?.trailing_stop || 0;
  const lastBarTime = tick?.last_bar_time || status?.last_bar_time || "";
  const winRate = tick?.win_rate ?? status?.win_rate ?? 0;
  const tradeCount = tick?.trade_count ?? status?.trade_count ?? 0;

  return {
    tick, status, indicators, trades, equity, candles, params,
    price, inPos, pv, entry, trail, lastBarTime,
    connected, winRate, tradeCount, fetchAll,
  };
}

function TfTab({ timeframe, active }) {
  const d = useTfData(timeframe);

  if (!active) return null;

  return (
    <div className="flex-1 flex flex-col gap-2 min-h-0">
      <TopBar
        asset="XAUUSD"
        price={d.price}
        connected={d.connected}
        lastBarTime={d.lastBarTime}
        timeframe={timeframe}
        inPos={d.inPos}
        pv={d.pv}
        tradeCount={d.tradeCount}
        winRate={d.winRate}
      />

      <div className="flex-1 grid grid-cols-1 xl:grid-cols-3 gap-2 min-h-0">
        {/* Col 1: Chart + Trade Log */}
        <div className="xl:col-span-2 flex flex-col gap-2 min-h-0">
          <MainChart
            candles={d.candles}
            timeframe={timeframe}
            indicators={d.indicators}
            trades={d.trades}
            entry={d.entry}
            trail={d.trail}
          />
          <TradeLog trades={d.trades} />
        </div>

        {/* Col 2: Status panels */}
        <div className="flex flex-col gap-2 min-h-0">
          <PositionStatus
            tick={d.tick}
            status={d.status}
            entry={d.entry}
            trail={d.trail}
          />
          <PortfolioPanel
            equity={d.equity}
            trades={d.trades}
            params={d.params}
            pv={d.pv}
          />
          <IndicatorTable indicators={d.indicators} />
          <ParamsPanel params={d.params} />
        </div>
      </div>
    </div>
  );
}

export default function App() {
  const [activeTf, setActiveTf] = useState("5m");

  return (
    <div className="min-h-screen bg-dark flex flex-col">
      {/* Global tab bar */}
      <div className="bg-gray-900 border-b border-gray-700 px-4 py-2 flex items-center gap-4 shrink-0">
        <span className="text-yellow-400 font-bold text-sm tracking-widest">XAUUSD</span>
        <div className="flex gap-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              onClick={() => setActiveTf(tf)}
              className={`px-4 py-1.5 rounded text-sm font-bold transition-colors ${
                activeTf === tf
                  ? "bg-yellow-500 text-black"
                  : "bg-gray-800 text-gray-400 hover:bg-gray-700"
              }`}
            >
              {tf.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Active tab content */}
      <div className="flex-1 p-2 min-h-0">
        {TIMEFRAMES.map((tf) => (
          <TfTab key={tf} timeframe={tf} active={tf === activeTf} />
        ))}
      </div>
    </div>
  );
}
