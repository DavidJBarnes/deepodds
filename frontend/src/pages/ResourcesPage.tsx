const sections: { heading: string; terms: { term: string; definition: string }[] }[] = [
  {
    heading: "Core Concepts",
    terms: [
      { term: "Asset / Pair", definition: "The thing you're trading. Also called a trading pair or product." },
      { term: "Position", definition: "An active trade you haven't closed yet. Closing (selling) the position realizes your profit or loss." },
      { term: "Entry", definition: "The moment you open a trade. Your entry price is what you paid. A good entry means buying at a low price relative to where it's headed." },
      { term: "Exit", definition: "The moment you close a trade by selling. The difference between your entry price and exit price determines your profit or loss." },
      { term: "Fill", definition: "When your order actually executes on the exchange. A market order fills immediately at the best available price. The fill price may differ slightly from what you saw." },
    ],
  },
  {
    heading: "Price & Market Data",
    terms: [
      { term: "Candle / Candlestick", definition: "A snapshot of price action over a time period. Each candle has an open (starting price), close (ending price), high, low, and volume." },
      { term: "Bid / Ask", definition: "The bid is the highest price a buyer is willing to pay. The ask is the lowest price a seller will accept. The difference between them is the spread." },
      { term: "Spread", definition: "The gap between the best bid and best ask price. Tighter spreads mean lower trading costs." },
      { term: "Slippage", definition: "The difference between the price you expected and the price you actually got. Happens with market orders, especially in fast-moving or illiquid markets." },
      { term: "Liquidity", definition: "How easily you can buy or sell without moving the price. High liquidity means tight spreads and minimal slippage. Low liquidity means wider spreads and your orders can move the market." },
      { term: "Volume", definition: "How much of an asset is being traded over a period. High volume means lots of buyers and sellers — more liquid, more reliable signals. Low volume can produce misleading price moves." },
      { term: "Volatility", definition: "How much the price swings. High volatility means big moves up and down. Higher volatility creates more trading opportunities but also more risk." },
    ],
  },

  {
    heading: "Risk Management",
    terms: [
      { term: "Stop Loss", definition: "An automatic exit that closes your position if losses exceed a threshold (default 3%). Protects you when the market moves against your position." },
      { term: "Position Size", definition: "How much money you risk per trade (default $25). Keeping this small and consistent means no single bad trade can wipe you out." },
      { term: "Daily Loss Limit", definition: "A circuit breaker that pauses all trading for the rest of the day if your total realized losses exceed a threshold. Prevents one bad day from spiraling." },
      { term: "Risk/Reward Ratio", definition: "How much you stand to gain vs. how much you could lose on a trade. A 2:1 ratio means you're targeting $2 of profit for every $1 of risk. Higher is better." },
      { term: "Drawdown", definition: "The decline from your peak account value to the lowest point before a new high. A 10% drawdown means you were down 10% from your best. Smaller drawdowns are easier to recover from." },
      { term: "Max Open Positions", definition: "The most positions the bot can hold at once (default 3). Limits how much capital is at risk simultaneously. If all 3 slots are filled, the bot won't enter new trades until one exits." },
      { term: "Diversification", definition: "Spreading risk across multiple assets or markets. If one position loses value, others may not — reducing overall portfolio risk." },
    ],
  },
  {
    heading: "Orders & Execution",
    terms: [
      { term: "Market Order", definition: "An order to buy or sell immediately at the best available price. Guaranteed to fill, but you might get a slightly worse price than shown." },
      { term: "Limit Order", definition: "An order to buy or sell at a specific price or better. Gives you price control but might not fill if the market doesn't reach your price." },
      { term: "Order Book", definition: "The list of all open buy and sell orders on an exchange. Shows the depth of supply and demand at each price level." },
    ],
  },
  {
    heading: "Performance",
    terms: [
      { term: "P&L (Profit & Loss)", definition: "Your net earnings or losses: (exit price - entry price) x quantity. Positive P&L = profit. Negative = loss. Displayed in dollars across the dashboard." },
      { term: "Realized P&L", definition: "Profit or loss from trades you've closed. This is real money gained or lost." },
      { term: "Unrealized P&L", definition: "Profit or loss on positions you still hold. Also called paper gains/losses. It's not real until you sell." },
      { term: "ROI (Return on Investment)", definition: "Total P&L divided by total capital deployed, as a percentage. 5% ROI on $100 invested means you made $5." },
      { term: "Win Rate", definition: "The percentage of trades that were profitable. A 60% win rate means 6 out of 10 trades made money. Win rate alone doesn't tell the whole story — you also need to consider how much you win vs. lose per trade." },
    ],
  },
  {
    heading: "Bot Modes",
    terms: [
      { term: "Paper Mode", definition: "Simulated trading with no real money. The bot generates signals and simulates fills against actual market prices. Use this to test your settings and build confidence before going live." },
      { term: "Live Mode", definition: "Real trading with real money on Kalshi. Orders are placed through the Kalshi Exchange API. Losses are real and irreversible. Requires Kalshi API keys." },
    ],
  },
];

export default function ResourcesPage() {
  return (
    <div className="space-y-8 max-w-3xl">
      <h2 className="text-2xl font-bold text-white">Resources</h2>

      <section className="space-y-6">
        <h3 className="text-lg font-semibold text-white">Glossary</h3>
        {sections.map((section) => (
          <div key={section.heading}>
            <h4 className="text-xs font-semibold uppercase tracking-wider text-emerald-400 mb-2 px-1">
              {section.heading}
            </h4>
            <div className="bg-slate-900 border border-slate-800 rounded-xl divide-y divide-slate-800">
              {section.terms.map((g) => (
                <div key={g.term} className="px-5 py-3">
                  <dt className="text-sm font-medium text-white">{g.term}</dt>
                  <dd className="text-sm text-slate-400 mt-0.5">{g.definition}</dd>
                </div>
              ))}
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}
