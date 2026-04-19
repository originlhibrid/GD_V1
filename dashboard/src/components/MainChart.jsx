import React, { useEffect, useRef } from 'react';
import { createChart } from 'lightweight-charts';

export default function MainChart({ candles, timeframe, indicators, trades, entry, trail }) {
  const chartRef = useRef(null);
  const seriesRef = useRef(null);
  const emaRef = useRef(null);
  const trailRef = useRef(null);
  const rocFastRef = useRef(null);
  const rocSlowRef = useRef(null);
  const momDecayRef = useRef(null);
  const containerRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current || !candles.length) return;

    const chart = createChart(containerRef.current, {
      layout: { background: { color: '#0f1117' }, textColor: '#9ca3af' },
      grid: { vertLines: { color: '#1f2937' }, horzLines: { color: '#1f2937' } },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: '#374151' },
      timeScale: { borderColor: '#374151', timeVisible: true },
      height: 480,
    });

    // Candlestick series
    const cs = chart.addCandlestickSeries({
      upColor: '#22c55e', downColor: '#ef4444',
      borderUpColor: '#22c55e', borderDownColor: '#ef4444',
      wickUpColor: '#22c55e', wickDownColor: '#ef4444',
    });

    const formatted = candles.map(c => ({
      time: c.timestamp?.replace(' ', 'T') + 'Z',
      open: c.open, high: c.high, low: c.low, close: c.close,
    }));
    cs.setData(formatted);
    chart.timeScale().fitContent();

    // EMA line (simplified — just close line as proxy)
    const emaLine = chart.addLineSeries({
      color: '#3b82f6', lineWidth: 1, title: 'EMA',
    });
    emaLine.setData(formatted.map(c => ({ time: c.time, value: c.close })));

    // Trailing stop line
    if (trail > 0) {
      const trailLine = chart.addLineSeries({
        color: '#f97316', lineWidth: 1, lineStyle: 2, title: 'Trail Stop',
      });
      trailLine.setData(formatted.map(c => ({ time: c.time, value: trail })));
    }

    // ROC sub-chart
    const rocChart = createChart(document.createElement('div'), {
      layout: { background: { color: '#0f1117' }, textColor: '#9ca3af' },
      grid: { vertLines: { color: '#1f2937' }, horzLines: { color: '#1f2937' } },
      rightPriceScale: { borderColor: '#374151' },
      timeScale: { visible: false },
      height: 120,
    });
    containerRef.current.parentElement.appendChild(rocChart.domElement());

    const rocFastSeries = rocChart.addLineSeries({ color: '#22c55e', title: 'ROC Fast' });
    const rocSlowSeries = rocChart.addLineSeries({ color: '#f97316', title: 'ROC Slow' });

    // Mom Decay histogram
    const momChart = createChart(document.createElement('div'), {
      layout: { background: { color: '#0f1117' }, textColor: '#9ca3af' },
      grid: { vertLines: { color: '#1f2937' }, horzLines: { color: '#1f2937' } },
      rightPriceScale: { borderColor: '#374151' },
      timeScale: { visible: false },
      height: 80,
    });
    const momSeries = momChart.addHistogramSeries({
      color: '#a855f7', title: 'Mom Decay',
    });

    seriesRef.current = cs;
    rocFastRef.current = rocFastSeries;
    rocSlowRef.current = rocSlowSeries;
    momDecayRef.current = momSeries;
    chartRef.current = chart;

    const handleResize = () => {
      if (containerRef.current)
        chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
      rocChart.remove();
      momChart.remove();
    };
  }, [candles.length]);

  // Update ROC + Mom Decay when indicators change
  useEffect(() => {
    if (!indicators || candles.length === 0) return;
    const lastCandle = candles[candles.length - 1];
    const time = lastCandle?.timestamp?.replace(' ', 'T') + 'Z';

    if (rocFastRef.current && time) {
      rocFastRef.current.update({ time, value: indicators.roc_fast || 0 });
      rocSlowRef.current.update({ time, value: indicators.roc_slow || 0 });
    }
    if (momDecayRef.current && time) {
      momDecayRef.current.update({
        time,
        value: indicators.mom_decay || 0,
        color: (indicators.mom_decay || 0) >= 0 ? '#22c55e' : '#ef4444',
      });
    }
  }, [indicators, candles]);

  return (
    <div className="bg-gray-900 border border-gray-700 rounded p-2">
      <div ref={containerRef} className="w-full" />
    </div>
  );
}
