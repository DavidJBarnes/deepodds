const glossary = [
  { term: "Settlement Arbitrage", definition: "A strategy that buys near-certain Kalshi contracts close to expiry when market makers still price tail risk into the premium. No directional prediction — pure mechanical edge from the temporal decay of risk premiums." },
  { term: "Binary Contract", definition: "A yes/no contract that pays out $1 (100 cents) if the condition is met, $0 if not. You buy at a price between 1-99 cents reflecting the market's implied probability. For example, 'BTC between $84,000 and $86,000 at 4pm' — if spot is in that range at expiry, YES wins." },
  { term: "Sigma Distance (σ)", definition: "How many standard deviations of price movement separate the current spot price from the nearest strike boundary, given the remaining time. 1σ = 84% chance of the boundary holding, 2σ = 98%, 3σ = 99.9%. Higher sigma means the outcome is more certain. The bot enters at 1.5σ+." },
  { term: "Realized Volatility", definition: "A measure of how much the price has actually been moving, computed from recent Binance trades. Unlike implied volatility (which is inflated by risk premiums), realized vol reflects actual recent price behavior. Used in the sigma distance calculation." },
  { term: "Volatility Risk Premium (VRP)", definition: "Option sellers demand extra compensation for bearing tail risk, so implied volatility systematically exceeds realized volatility by 10-30 points. This is why the old BSM model generated phantom edges — it used inflated IV as input. The settlement arb strategy avoids this entirely." },
  { term: "Fair Value", definition: "What a contract is worth based on the actual probability of winning. Computed as P(win) × 100¢, where P(win) comes from the sigma distance. If sigma = 2.0, P(win) = 97.7%, so fair value = 97.7¢." },
  { term: "Discount", definition: "The difference between fair value and the market ask price. If fair value is 97¢ and the market asks 90¢, the discount is 7¢. This is our edge — we buy below fair value. The bot requires a minimum discount of 5¢ to enter." },
  { term: "Expected Value (EV)", definition: "The average profit per contract after accounting for win probability, payout, and Kalshi fees. The bot only enters when EV is positive. Example: 97.7% chance of winning 8¢ net = +7.8¢ EV per contract." },
  { term: "Spot Price", definition: "The current market price of the underlying asset (e.g., Bitcoin at $85,500). Sourced from Binance in real-time via websocket." },
  { term: "Strike Price / Range", definition: "The threshold or range in the contract. 'BTC above $84,000' has strike = $84,000. 'BTC between $84,000 and $86,000' has a low strike and a cap strike. Contracts can be 'above', 'below', or 'between' (range)." },
  { term: "Max Exposure", definition: "The maximum total dollar amount tied up in open (unsettled) positions at any time. When positions settle, that capital is freed for new trades. Acts as a rolling risk cap." },
  { term: "Daily Budget", definition: "An optional hard cap on total spending per calendar day, regardless of outcomes. 0 = unlimited. When enabled, no new signals are created once the day's spend hits this limit." },
  { term: "Daily Loss Limit", definition: "A circuit breaker that pauses the bot for the rest of the day if realized losses exceed this threshold. Prevents a bad day from spiraling. 0 = disabled." },
  { term: "Limit Price", definition: "The maximum price you're willing to pay for a contract. In settlement arb, this is typically the ask price of the near-certain side — since we're buying at a discount, the ask IS below fair value." },
  { term: "Kelly-Inspired Sizing", definition: "Position sizing that allocates more capital to higher-edge trades. The bot uses 5-25% of the configured max position, proportional to the discount. A 15¢ discount gets a bigger bet than a 5¢ discount." },
  { term: "Paper Mode", definition: "Simulated trading that doesn't use real money. Signals are generated and fills are simulated against actual market ask prices. Settlement uses real spot vs strike. Use this to evaluate the strategy before going live." },
  { term: "Live Mode", definition: "Real trading with actual money on Kalshi. Orders are placed via the Kalshi API using your RSA-signed API keys. Losses are real and irreversible." },
  { term: "Kalshi Fees", definition: "Kalshi charges 7% of profit per contract on winning trades, with a minimum of 2 cents per contract. Losing trades are not charged fees. The bot accounts for this in every expected value calculation — it won't enter a trade unless EV is positive after fees." },
  { term: "Max Signals Per Hour", definition: "A pacing control that caps how many new signals can be created in any rolling 60-minute window. Settlement arb is naturally low-frequency (2-8 trades/day), so this mainly acts as a safety valve in unusual market conditions." },
  { term: "Settled", definition: "A contract that has reached its expiry time. The outcome is determined by comparing the final spot price vs the strike price or range at settlement time. Most settlement arb positions resolve in 15-60 minutes." },
  { term: "P&L (Profit & Loss)", definition: "Net earnings or losses on a trade: (payout - entry cost - Kalshi fees). Displayed in dollars across the dashboard, signal table, and P&L chart." },
  { term: "ROI (Return on Investment)", definition: "Total P&L divided by total capital invested, as a percentage. Shows how efficiently your capital is being deployed. Settlement arb targets 1-8% per trade over short holding periods." },
  { term: "Win Rate", definition: "Percentage of settled trades that won. Settlement arb targets 85-95% win rates — most trades win small amounts, with occasional losses on the rare tail events that breach the sigma distance." },
  { term: "Near-Expiry Contracts", definition: "The dashboard table showing contracts expiring within 2 hours. These are candidates the bot is evaluating. The predicted side (YES/NO) is shown based on current spot position relative to strike boundaries." },
];

const faqs = [
  {
    q: "How does the bot decide what to buy?",
    a: "Every 60 seconds, the scanner fetches all active crypto contracts from Kalshi. For contracts expiring within the configured window (default 60 minutes), it computes a sigma distance — how many standard deviations of price movement separate spot from the nearest strike boundary. If sigma ≥ 1.5 (93%+ win probability) and the near-certain side trades below fair value by the minimum discount, a buy signal is generated.",
  },
  {
    q: "What's sigma distance and why does it matter?",
    a: "Sigma distance measures how statistically safe a bet is. If BTC is at $85,500 and the contract says 'BTC above $84,000' with 45 minutes left, that's about 2-3σ away — meaning there's a 98-99.9% chance BTC stays above $84K. The bot enters when sigma is high enough that the edge from market mispricing outweighs the tiny risk of a fat-tail event.",
  },
  {
    q: "How does settlement work?",
    a: "At the contract's close time, the bot compares the final spot price against the strike or range. If you bought YES on 'BTC between $84K-$86K' and spot is $85,500 at expiry, you win — the $1 contract pays out. If spot is $83,000 (below the range), you lose. Most positions resolve in 15-60 minutes.",
  },
  {
    q: "Can I lose money?",
    a: "Yes. Even at 97% win probability, 3% of trades will lose. That's the nature of probability — sigma distance measures likelihood, not certainty. A sudden 5% BTC wick (the 'fat tail') can breach even a 3σ boundary. This is why position sizing and risk controls exist: you win most trades by small amounts and occasionally lose one. Over time, the expected value is positive.",
  },
  {
    q: "What's the difference between paper and live mode?",
    a: "Paper mode simulates everything — fills against real ask prices, settlement against real spot at expiry. No real money at risk. Live mode places actual Kalshi orders using your API keys. Use paper mode to verify the strategy works before committing capital.",
  },
  {
    q: "Why do I need Kalshi API keys?",
    a: "API keys are needed for live trading — they allow the bot to place and manage orders on your behalf. They use RSA signing for security and are stored server-side. Generate them at kalshi.com under Account → API Keys. The bot also uses them to display your Kalshi account balance.",
  },
  {
    q: "How are Kalshi fees calculated?",
    a: "Kalshi charges 7% of profit per contract, with a 2¢ minimum. If you buy at 90¢ and win (payout 100¢), profit is 10¢, fee is max(2, 10×0.07) = 2¢, net = 8¢. On a losing trade (profit = 0), there's no fee. The bot accounts for this in every expected value calculation.",
  },
  {
    q: "Why did you switch from the old BSM model to settlement arb?",
    a: "The old model used Black-Scholes with Deribit implied volatility to compute 'fair' probabilities. But implied volatility is systematically 10-30 points higher than what actually happens — option sellers charge a premium for tail risk. This created phantom edges: the model thought it found underpriced contracts, but the market was right and the model was wrong. Settlement arb avoids this entirely — no probability model, no IV dependency.",
  },
  {
    q: "How does the bot protect against big losses?",
    a: "Three layers: (1) Max exposure caps total capital in open positions. (2) The daily loss circuit breaker pauses all trading if realized losses exceed your limit. (3) Per-ticker cooldowns prevent re-entering a contract you just lost on. Plus, settlement arb's high win rate means you're taking many small wins and occasional small losses — there shouldn't be 'big' losses unless you size positions too aggressively.",
  },
  {
    q: "What's the difference between the near-expiry table and the signals table?",
    a: "The near-expiry table (top) shows contracts the scanner found that expire within 2 hours — these are candidates the bot is evaluating. The signals table (bottom) shows actual trades the bot placed. Think of the near-expiry table as your 'watch list' and the signals table as your 'trade history.'",
  },
  {
    q: "How many trades should I expect?",
    a: "Settlement arb is naturally low-frequency. Expect 2-8 signals per day across all BTC and ETH contracts. This isn't a high-frequency strategy — it's about finding specific moments where market prices lag reality. Each trade resolves in 15-60 minutes, so capital turns over quickly.",
  },
  {
    q: "What are the three strategies in settings?",
    a: "Settlement Arb is the primary strategy described above. Naive NO is a baseline control — it buys NO on any range contract under 8¢ with no model at all, to test if the alpha is structural. BSM Model (V1) is the old Black-Scholes approach kept for historical comparison. Only one is active at a time.",
  },
  {
    q: "Where do prices and volatility data come from?",
    a: "Spot BTC and ETH prices stream in real-time from Binance via websocket. Realized volatility is computed from Binance 1-hour klines at 1-minute granularity. Contract data (strikes, prices, close times) comes from Kalshi's public API.",
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
