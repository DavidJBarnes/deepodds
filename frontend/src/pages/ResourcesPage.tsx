const glossary = [
  { term: "Binary Contract", definition: "A yes/no contract that pays out $1 (100 cents) if the condition is met, $0 if not. You buy at a price between 1-99 cents reflecting the market's implied probability." },
  { term: "Yes / No Side", definition: "Buying YES means you think the event will happen (e.g., BTC above $76,000). Buying NO means you think it won't. The YES and NO prices always add up to $1." },
  { term: "Edge", definition: "The difference between the model's fair value and the market price. Positive edge means the model thinks the contract is underpriced — a potential buying opportunity." },
  { term: "Fair Value", definition: "What the model calculates a contract is worth based on Black-Scholes probability, using current spot price, strike price, time to expiry, and implied volatility." },
  { term: "Implied Volatility (IV)", definition: "A measure of how much the market expects the price to move. Higher IV means wider expected price swings. DeepOdds sources IV from Deribit's DVOL index." },
  { term: "Spot Price", definition: "The current market price of the underlying asset (e.g., Bitcoin at $76,500). Sourced from Binance in real-time." },
  { term: "Strike Price", definition: "The threshold price in the contract. For example, 'BTC above $76,000' has a strike of $76,000. If spot > strike at expiry, YES wins." },
  { term: "Max Exposure", definition: "The maximum total dollar amount you can have tied up in open (unsettled) positions at any time. Unlike a daily budget, exposure is freed when positions settle — so winning trades release capital for new bets throughout the day." },
  { term: "Daily Budget", definition: "An optional hard cap on total spending per day, regardless of outcomes. Set to $0 to disable. When enabled, no new signals are created once the day's total spend hits this limit, even if exposure has been freed by settled positions." },
  { term: "Limit Price", definition: "The maximum price you're willing to pay for a contract. The bot sets this based on the model's fair value to ensure you only buy at prices with positive edge." },
  { term: "Fill Price", definition: "The actual price at which an order was executed. In paper mode, this simulates when the market ask drops to or below your limit price." },
  { term: "Take Profit", definition: "An automatic exit strategy. When the unrealized profit per contract reaches your threshold (e.g., 15 cents), the position is sold early rather than waiting for expiry." },
  { term: "Settled", definition: "A contract that has reached its expiry time. The outcome is determined by comparing spot price vs strike price at settlement time." },
  { term: "P&L (Profit & Loss)", definition: "Your net earnings or losses on a trade, calculated as (exit price - entry price) × quantity, minus Kalshi's transaction fees." },
  { term: "ROI (Return on Investment)", definition: "Total P&L divided by total cost, expressed as a percentage. Shows how efficiently your capital is being deployed." },
  { term: "Liquidity", definition: "How many contracts are available on the order book. Low liquidity means harder fills and more price impact. The bot filters out markets below your minimum liquidity threshold." },
  { term: "Paper Mode", definition: "Simulated trading that doesn't use real money. Signals are generated and fills are simulated based on actual market prices, so you can evaluate the strategy before going live." },
  { term: "Live Mode", definition: "Real trading with actual money on Kalshi. Orders are placed via the Kalshi API using your RSA-signed API keys." },
  { term: "Edge Tier", definition: "A classification of signal quality based on edge magnitude. Elite (80c+), High (50-79c), Moderate (20-49c), Speculative (<20c). Higher tiers get larger position sizes." },
  { term: "Kalshi Fees", definition: "Kalshi charges 7% of profit per contract on winning trades, with a minimum of 2 cents per contract. Losing trades are not charged fees. DeepOdds accounts for this in all P&L calculations." },
  { term: "Stop Loss", definition: "An automatic exit strategy that limits downside. When the unrealized loss per contract on a filled position reaches or exceeds your stop-loss threshold (e.g., 10 cents), the position is sold immediately at the current bid price to prevent further losses." },
  { term: "Daily Loss Limit", definition: "A circuit breaker that pauses signal generation for the rest of the day if your total realized losses exceed the configured threshold. The bot remains enabled but skips evaluation until the next day, preventing a bad day from spiraling." },
  { term: "Max Signals Per Hour", definition: "A pacing control that caps how many new signals can be created in any rolling 60-minute window. This spreads your daily budget across the trading day instead of front-loading all positions in the first evaluation cycles." },
  { term: "Tier Budget Reservation", definition: "Reserves a percentage of your daily budget exclusively for high-confidence (high and elite tier) signals. Speculative and moderate signals can only use the unreserved portion, ensuring that when a strong opportunity appears, budget is available for it." },
  { term: "Spot Trading", definition: "Buying and selling actual BTC (not prediction contracts). DeepOdds uses a 'buy the dip' strategy — automatically purchasing BTC when the price drops from its recent high, and selling when it recovers or hits a stop loss." },
  { term: "Dip Threshold", definition: "The percentage drop from BTC's rolling 1-hour high that triggers a buy. For example, a 3% threshold means the bot buys when BTC falls 3% from its highest price in the last hour." },
  { term: "Rolling 1-Hour High", definition: "The highest BTC price observed in the last 60 minutes, tracked in real-time via Binance websocket. This is the reference point for calculating dip percentage." },
  { term: "Cooldown", definition: "The minimum wait time between successive spot dip buys. Prevents the bot from buying repeatedly during a sustained drop. Default is 60 minutes." },
  { term: "Max Position (Spot)", definition: "The maximum total USD invested in BTC at any time. Once this limit is reached, no more dip buys are placed until the position is closed." },
  { term: "Cost Basis", definition: "The total USD spent building your BTC position. When multiple dip buys occur, the entry price is the weighted average across all buys." },
  { term: "Coinbase Advanced Trade API", definition: "The API used by DeepOdds for live spot BTC execution. Requires an API key and secret from your Coinbase account under Settings > API." },
  { term: "Binance Websocket", definition: "A persistent real-time connection to Binance that streams BTC trade data. Provides sub-second price updates used for the dip meter and spot trading decisions." },
];

const faqs = [
  {
    q: "How does the bot decide what to buy?",
    a: "Every 60 seconds, the scanner fetches all active crypto contracts from Kalshi and computes a probability for each using a Black-Scholes model with real-time implied volatility from Deribit. If the model's fair value exceeds the market price by more than your configured edge threshold, a buy signal is generated.",
  },
  {
    q: "What does 'edge' mean and why does it matter?",
    a: "Edge is the difference between what the model thinks a contract is worth and what the market is asking. For example, if the model says a contract is worth 30 cents but the market price is 18 cents, that's 12 cents of edge. Higher edge generally means higher confidence and better risk/reward.",
  },
  {
    q: "When does the bot sell?",
    a: "Two ways: (1) Take-profit — if the position's unrealized profit per contract reaches your threshold, it sells early to lock in gains. (2) Expiry settlement — at contract close time, the outcome is determined by whether the spot price is above or below the strike.",
  },
  {
    q: "Can I lose money?",
    a: "Yes. If you buy a YES contract at 20 cents and the underlying doesn't reach the strike price, you lose the full 20 cents per contract. The model identifies statistical edges, but individual trades can and will lose. That's why position sizing and risk management matter.",
  },
  {
    q: "What's the difference between paper and live mode?",
    a: "Paper mode simulates everything — fills are checked against real market ask prices, take-profits against real bids, and settlement against real spot prices. No actual orders are placed and no real money is at risk. Use it to evaluate the strategy before committing capital.",
  },
  {
    q: "Why do I need Kalshi API keys?",
    a: "API keys are needed for live trading — they allow the bot to place and manage orders on your behalf. They're also needed to display your Kalshi account balance. Keys use RSA signing for security and are stored server-side. Generate them at kalshi.com under Account > API Keys.",
  },
  {
    q: "How are fees calculated?",
    a: "Kalshi charges 7% of profit per contract on winning trades, with a 2-cent minimum per contract. So if you buy at 10 cents and sell/settle at 30 cents (20 cents profit), the fee is max(2, 20×0.07) = 2 cents per contract. Losing trades have no fee.",
  },
  {
    q: "What do the edge tiers mean?",
    a: "Tiers classify signals by edge strength: Elite (80c+) are rare high-conviction bets, High (50-79c) are strong, Moderate (20-49c) are average, Speculative (<20c) are lower confidence. Each tier can have different position size limits in settings.",
  },
  {
    q: "How does the bot protect against big losses?",
    a: "Three layers work together: (1) Max exposure caps how much capital can be in open positions at once — settled positions free up room for new trades. (2) Per-position stop-loss exits any individual position once its unrealized loss per contract hits your threshold. (3) The daily loss circuit breaker pauses all new signal generation if your total realized losses for the day exceed your configured limit. Together these ensure you never risk more than you're comfortable with.",
  },
  {
    q: "What's the difference between max exposure and daily budget?",
    a: "Max exposure limits how much is at risk right now — it's a rolling cap on open positions. When a position settles (win or lose), that capital is freed and the bot can open new positions. Daily budget is an optional hard ceiling on total spending for the day, regardless of outcomes. Most users set max exposure as their primary control and leave daily budget at $0 (disabled).",
  },
  {
    q: "How does spot BTC trading work?",
    a: "The bot streams BTC prices in real-time from Binance and tracks the highest price in the last hour. When the price drops by your configured dip threshold (default 3%), it buys a fixed dollar amount of BTC. If the price recovers past your take-profit percentage, it sells for a gain. If it drops further past your stop-loss, it sells to limit the loss. Multiple dip buys can accumulate into one position (dollar-cost averaging), up to your max position limit.",
  },
  {
    q: "What's the difference between Kalshi trading and spot BTC?",
    a: "Kalshi trading buys binary prediction contracts — you're betting on whether BTC will be above or below a price at a specific time. Spot trading buys actual BTC — you own the asset and profit from price movements directly. Both run in parallel with separate settings, but their P&L is combined in the dashboard stats.",
  },
  {
    q: "Do I need a Coinbase account for spot trading?",
    a: "Only for live mode. In paper mode, the bot simulates trades against real Binance prices without placing any real orders. When you're ready for live spot trading, you'll need a Coinbase account with API keys (Settings > Coinbase API Keys). The bot uses Coinbase's Advanced Trade API for market orders.",
  },
  {
    q: "Why does the bot use Binance for prices but Coinbase for orders?",
    a: "Binance provides the fastest, most liquid BTC price stream via websocket — ideal for real-time dip detection. Coinbase Advanced Trade is used for execution because it offers a straightforward US-regulated exchange with a reliable REST API for market orders. The price difference between the two is negligible for the timeframes involved.",
  },
  {
    q: "What happens if BTC keeps falling after a dip buy?",
    a: "The cooldown timer (default 60 minutes) prevents immediate repeat buys. If the price is still dipping after the cooldown and your position is under the max limit, the bot will buy again — averaging down your entry price. If the total drop exceeds your stop-loss threshold, the entire position is sold to cap losses.",
  },
];

export default function ResourcesPage() {
  return (
    <div className="space-y-8 max-w-3xl">
      <h2 className="text-2xl font-bold text-white">Resources</h2>

      <section className="space-y-4">
        <h3 className="text-lg font-semibold text-white">Glossary</h3>
        <div className="bg-slate-900 border border-slate-800 rounded-xl divide-y divide-slate-800">
          {glossary.map((g) => (
            <div key={g.term} className="px-5 py-3">
              <dt className="text-sm font-medium text-emerald-400">{g.term}</dt>
              <dd className="text-sm text-slate-400 mt-0.5">{g.definition}</dd>
            </div>
          ))}
        </div>
      </section>

      <section className="space-y-4">
        <h3 className="text-lg font-semibold text-white">FAQ</h3>
        <div className="space-y-3">
          {faqs.map((f) => (
            <details key={f.q} className="bg-slate-900 border border-slate-800 rounded-xl group">
              <summary className="px-5 py-3 text-sm font-medium text-white cursor-pointer hover:text-emerald-400 transition-colors">
                {f.q}
              </summary>
              <p className="px-5 pb-4 text-sm text-slate-400">{f.a}</p>
            </details>
          ))}
        </div>
      </section>
    </div>
  );
}
