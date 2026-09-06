import type { Fundamentals } from '../types'
import { crore, dateIST, inr, pct, ratio } from '../format'

/** The numbers a watchlist is expected to show: valuation, profitability,
 *  leverage, payout.
 *
 *  Two rules run through this whole block. First, a dash is a real answer — a
 *  loss-making company has no trailing P/E, and printing "0.0" there would be
 *  a lie dressed as data. Second, the source and the quarter it came from are
 *  shown alongside the numbers, not buried: these are the only figures in the
 *  app that come from a vendor endpoint we cannot always reach, and the user
 *  deserves to know which quarter they are reading. */

const HELP: Record<string, string> = {
  mcap: 'Total value of the company: share price × number of shares. Large-caps are usually steadier; small-caps move more.',
  pe: 'Price ÷ earnings per share. Roughly "how many years of current profit you are paying for one share". High can mean expensive, or fast-growing. A loss-making company has none.',
  fpe: 'The same ratio using analysts\' forecast earnings for next year instead of last year\'s.',
  pb: 'Price ÷ book value per share. Book value is what the company owns minus what it owes, per share.',
  eps: 'Earnings per share: profit for the last twelve months divided by the number of shares.',
  roe: 'Return on equity: profit as a percentage of shareholders\' money in the business. Higher generally means the company uses its capital well.',
  dy: 'Dividend yield: the last year of dividends as a percentage of today\'s price.',
  de: 'Debt ÷ equity, as a percentage. How much of the business is funded by borrowing. High means more risk if profits fall.',
  pm: 'Profit margin: what fraction of revenue ends up as profit.',
  growth: 'Revenue growth over the same quarter a year earlier.',
  beta: 'How much this stock tends to move when the market moves. Above 1 = swings more than the index.',
}

function Cell({ label, help, value, tone }: { label: string; help: string; value: string; tone?: 'up' | 'down' }) {
  return (
    <div className="fcell">
      <div className="fk" title={help}>{label}</div>
      <div className={`fv num ${value === '—' ? 'none' : tone ?? ''}`}>{value}</div>
    </div>
  )
}

export function FundamentalsBlock({ f }: { f: Fundamentals | null }) {
  if (!f) {
    return (
      <div className="fundamentals">
        <h4>Fundamentals</h4>
        <div className="faint small">
          Not available for this stock from the free feed. Rather than show blanks that look like
          data, Since leaves them out — see the README on why P/E and ROE are the one part of this
          app that depends on an endpoint the vendor gates.
        </div>
      </div>
    )
  }
  const tone = (x: number | null) => (x == null ? undefined : x >= 0 ? 'up' as const : 'down' as const)
  return (
    <div className="fundamentals">
      <h4>
        Fundamentals
        <span className="faint" style={{ fontWeight: 400, letterSpacing: 0, textTransform: 'none' }}>
          · hover a label for what it means
        </span>
      </h4>
      <div className="fgrid">
        <Cell label="Market cap" help={HELP.mcap} value={crore(f.market_cap)} />
        <Cell label="P/E" help={HELP.pe} value={ratio(f.pe_trailing)} />
        <Cell label="P/E (fwd)" help={HELP.fpe} value={ratio(f.pe_forward)} />
        <Cell label="P/B" help={HELP.pb} value={ratio(f.price_to_book, 2)} />
        <Cell label="EPS" help={HELP.eps} value={f.eps_trailing == null ? '—' : inr(f.eps_trailing)} />
        <Cell label="ROE" help={HELP.roe} value={f.roe == null ? '—' : pct(f.roe, false)} tone={tone(f.roe)} />
        <Cell label="Margin" help={HELP.pm} value={f.profit_margin == null ? '—' : pct(f.profit_margin, false)} tone={tone(f.profit_margin)} />
        <Cell label="Revenue" help={HELP.growth} value={f.revenue_growth == null ? '—' : pct(f.revenue_growth)} tone={tone(f.revenue_growth)} />
        <Cell label="Debt/equity" help={HELP.de} value={f.debt_to_equity == null ? '—' : `${f.debt_to_equity.toFixed(0)}%`} />
        <Cell label="Div. yield" help={HELP.dy} value={f.dividend_yield == null ? '—' : pct(f.dividend_yield, false)} />
        <Cell label="Beta" help={HELP.beta} value={ratio(f.beta, 2)} />
      </div>
      <div className="faint small fsrc">
        {f.as_of ? <>Company figures as reported for the quarter ending <b>{dateIST(f.as_of)}</b>. </> : null}
        Source: {f.source}, fetched {dateIST(f.fetched_at)}. A dash means the feed had no value for
        that field — not a zero.
      </div>
    </div>
  )
}
