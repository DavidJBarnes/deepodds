import { useEffect, useRef } from "react";
import { useBotStore } from "@/stores/botStore";
import type { SpotPnLStats, SpotPosition, SpotTrade } from "@/api/bot";

function PriceDisplay({ price, prevPrice }: { price: number | null; prevPrice: number | null }) {
  if (price === null) return <span className="text-slate-500">Connecting...</span>;
  const direction = prevPrice !== null ? (price > prevPrice ? "up" : price < prevPrice ? "down" : null) : null;
  return (
    <span className={`text-3xl font-bold tabular-nums transition-colors duration-300 ${
      direction === "up" ? "text-emerald-400" : direction === "down" ? "text-red-400" : "text-white"
    }`}>
      ${price.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
    </span>
  );
}

function TriggerMeter({
  dipPct,
  dipThreshold,
  takeProfitPct,
  stopLossPct,
  position,
  currentPrice,
  high4h,
}: {
  dipPct: number | null;
  dipThreshold: number;
  takeProfitPct: number;
  stopLossPct: number;
  position: SpotPosition | null;
  currentPrice: number | null;
  high4h: number | null;
}) {
  const hasPosition = position !== null && currentPrice !== null;

  const leftLabel = hasPosition ? `Stop -${stopLossPct}%` : `Buy -${dipThreshold}%`;
  const rightLabel = hasPosition ? `Sell +${takeProfitPct}%` : `Sell +${takeProfitPct}%`;

  let pct = 0;
  let leftMax = dipThreshold;
  let rightMax = takeProfitPct;

  if (hasPosition) {
    pct = ((currentPrice - position.entry_price_usd) / position.entry_price_usd) * 100;
    leftMax = stopLossPct;
    rightMax = takeProfitPct;
  } else {
    pct = -(dipPct ?? 0);
  }

  const leftFill = pct < 0 ? Math.min(100, (Math.abs(pct) / Math.max(leftMax, 0.01)) * 100) : 0;
  const rightFill = pct > 0 ? Math.min(100, (pct / Math.max(rightMax, 0.01)) * 100) : 0;
  const leftTriggered = pct < 0 && Math.abs(pct) >= leftMax;
  const rightTriggered = pct > 0 && pct >= rightMax;

  const high4hStr = high4h ? ` ($${high4h.toLocaleString(undefined, { maximumFractionDigits: 0 })})` : "";
  const statusText = hasPosition
    ? `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}% from entry`
    : `${(dipPct ?? 0).toFixed(2)}% dip from 4h high${high4hStr}`;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
      <div className="flex justify-between text-xs text-slate-400 mb-2">
        <span className={leftTriggered ? "text-red-400 font-medium" : ""}>{leftLabel}</span>
        <span className={
          leftTriggered ? "text-red-400 font-medium"
          : rightTriggered ? "text-emerald-400 font-medium"
          : ""
        }>
          {statusText}
        </span>
        <span className={rightTriggered ? "text-emerald-400 font-medium" : ""}>{rightLabel}</span>
      </div>
      <div className="relative h-3 flex gap-0.5">
        <div className="flex-1 bg-slate-800 rounded-l-full overflow-hidden">
          <div
            className={`h-full float-right rounded-l-full transition-all duration-500 ${
              leftTriggered ? "bg-red-500" : "bg-amber-500"
            }`}
            style={{ width: `${leftFill}%` }}
          />
        </div>
        <div className="w-0.5 bg-slate-500 rounded-full shrink-0" />
        <div className="flex-1 bg-slate-800 rounded-r-full overflow-hidden">
          <div
            className={`h-full rounded-r-full transition-all duration-500 ${
              rightTriggered ? "bg-emerald-400" : "bg-emerald-500"
            }`}
            style={{ width: `${rightFill}%` }}
          />
        </div>
      </div>
      {leftTriggered && !hasPosition && (
        <p className="text-xs text-amber-400 mt-1">Dip threshold reached — buy signal active</p>
      )}
      {leftTriggered && hasPosition && (
        <p className="text-xs text-red-400 mt-1">Stop loss triggered</p>
      )}
      {rightTriggered && (
        <p className="text-xs text-emerald-400 mt-1">Take profit triggered</p>
      )}
    </div>
  );
}

function PositionCard({ position, currentPrice }: { position: SpotPosition | null; currentPrice: number | null }) {
  if (!position) {
    return (
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <p className="text-sm text-slate-500">No open position</p>
      </div>
    );
  }
  const unrealized = currentPrice
    ? (currentPrice - position.entry_price_usd) * position.quantity_btc
    : position.unrealized_pnl_usd ?? 0;
  const changePct = currentPrice
    ? ((currentPrice - position.entry_price_usd) / position.entry_price_usd) * 100
    : 0;
  const positive = unrealized >= 0;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-xl p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-500 uppercase tracking-wide">Open Position</span>
        <span className={`text-xs font-medium px-2 py-0.5 rounded ${
          positive ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"
        }`}>
          {positive ? "+" : ""}{changePct.toFixed(2)}%
        </span>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <p className="text-xs text-slate-500">Entry</p>
          <p className="text-sm text-white font-medium">
            ${position.entry_price_usd.toLocaleString(undefined, { maximumFractionDigits: 2 })}
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Quantity</p>
          <p className="text-sm text-white font-medium">{position.quantity_btc.toFixed(6)} BTC</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Cost Basis</p>
          <p className="text-sm text-white font-medium">${position.cost_basis_usd.toFixed(2)}</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Unrealized P&L</p>
          <p className={`text-sm font-medium ${positive ? "text-emerald-400" : "text-red-400"}`}>
            {positive ? "+" : ""}${unrealized.toFixed(2)}
          </p>
        </div>
      </div>
    </div>
  );
}

function TradeRow({ trade }: { trade: SpotTrade }) {
  const time = new Date(trade.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const date = new Date(trade.created_at).toLocaleDateString([], { month: "short", day: "numeric" });
  const triggerLabel: Record<string, string> = {
    dip: "Dip Buy",
    take_profit: "Take Profit",
    stop_loss: "Stop Loss",
    manual: "Manual",
  };
  return (
    <tr className="border-t border-slate-800/50">
      <td className="py-2 px-3 text-xs text-slate-400">{date} {time}</td>
      <td className="py-2 px-3">
        <span className={`text-xs font-medium px-1.5 py-0.5 rounded ${
          trade.side === "buy" ? "bg-emerald-500/20 text-emerald-400" : "bg-red-500/20 text-red-400"
        }`}>
          {trade.side.toUpperCase()}
        </span>
      </td>
      <td className="py-2 px-3 text-xs text-white tabular-nums">
        ${trade.price_usd.toLocaleString(undefined, { maximumFractionDigits: 2 })}
      </td>
      <td className="py-2 px-3 text-xs text-slate-400 tabular-nums">${trade.amount_usd.toFixed(2)}</td>
      <td className="py-2 px-3 text-xs text-slate-400">{triggerLabel[trade.trigger] ?? trade.trigger}</td>
      <td className="py-2 px-3 text-xs tabular-nums">
        {trade.pnl_usd !== null ? (
          <span className={trade.pnl_usd >= 0 ? "text-emerald-400" : "text-red-400"}>
            {trade.pnl_usd >= 0 ? "+" : ""}${trade.pnl_usd.toFixed(2)}
          </span>
        ) : (
          <span className="text-slate-600">—</span>
        )}
      </td>
    </tr>
  );
}

export default function SpotTab({ spotStats, spotEnabled, dipThreshold = 3.0, takeProfitPct = 3.0, stopLossPct = 2.0 }: { spotStats: SpotPnLStats | null; spotEnabled: boolean; dipThreshold?: number; takeProfitPct?: number; stopLossPct?: number }) {
  const { spotPrice, spotHigh1h, spotHigh4h, spotDipPct, spotDipPct4h, spotTrades, spotPosition, fetchSpotData, startPriceStream } = useBotStore();
  const prevPriceRef = useRef<number | null>(null);
  const prevPrice = prevPriceRef.current;

  useEffect(() => {
    if (spotPrice !== null) prevPriceRef.current = spotPrice;
  }, [spotPrice]);

  useEffect(() => {
    const cleanup = startPriceStream();
    fetchSpotData();
    const interval = setInterval(fetchSpotData, 30000);
    return () => {
      cleanup();
      clearInterval(interval);
    };
  }, [startPriceStream, fetchSpotData]);

  return (
    <div className="space-y-4">
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-4">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-xs text-slate-500 uppercase tracking-wide mb-1">BTC / USD</p>
            <PriceDisplay price={spotPrice} prevPrice={prevPrice} />
          </div>
          {spotStats && (
            <div className="text-right space-y-1">
              <div>
                <p className="text-xs text-slate-500">Realized P&L</p>
                <p className={`text-sm font-medium ${
                  spotStats.realized_pnl_usd >= 0 ? "text-emerald-400" : "text-red-400"
                }`}>
                  {spotStats.realized_pnl_usd >= 0 ? "+" : ""}${spotStats.realized_pnl_usd.toFixed(2)}
                </p>
              </div>
              <div>
                <p className="text-xs text-slate-500">Trades</p>
                <p className="text-sm font-medium text-white">{spotStats.total_trades}</p>
              </div>
            </div>
          )}
        </div>
      </div>

      <TriggerMeter dipPct={spotDipPct4h} dipThreshold={dipThreshold} takeProfitPct={takeProfitPct} stopLossPct={stopLossPct} position={spotPosition} currentPrice={spotPrice} high4h={spotHigh4h} />
      <PositionCard position={spotPosition} currentPrice={spotPrice} />

      {spotTrades.length > 0 && (
        <div className="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden">
          <table className="w-full text-left">
            <thead>
              <tr className="bg-slate-800/50">
                <th className="py-2 px-3 text-xs text-slate-500 font-medium">Time</th>
                <th className="py-2 px-3 text-xs text-slate-500 font-medium">Side</th>
                <th className="py-2 px-3 text-xs text-slate-500 font-medium">Price</th>
                <th className="py-2 px-3 text-xs text-slate-500 font-medium">Amount</th>
                <th className="py-2 px-3 text-xs text-slate-500 font-medium">Trigger</th>
                <th className="py-2 px-3 text-xs text-slate-500 font-medium">P&L</th>
              </tr>
            </thead>
            <tbody>
              {spotTrades.map((t) => <TradeRow key={t.id} trade={t} />)}
            </tbody>
          </table>
        </div>
      )}

      {spotTrades.length === 0 && (
        <div className="text-center py-8 text-slate-500 text-sm">
          {spotEnabled
            ? "No spot trades yet. Waiting for a dip to trigger a buy."
            : "No spot trades yet. Enable spot trading in Settings to get started."}
        </div>
      )}
    </div>
  );
}
