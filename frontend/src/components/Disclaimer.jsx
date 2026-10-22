import { useEffect, useRef } from 'react'

// One source of truth for every disclaimer shown in the app (open notice, header strip, footer).
export const SHORT_NOTICE =
  'For educational purposes only · Not investment advice · Not a SEBI-registered adviser or research analyst · Trading in F&O involves substantial risk'

export function DisclaimerText() {
  return (
    <>
      <p><b>For educational purposes only.</b> NSE Stock Analyzer is a learning tool. Nothing in it is investment, trading, tax or legal
        advice, or a recommendation to buy, sell or hold any security, derivative or index.</p>
      <ul>
        <li>This app is not registered with SEBI as an Investment Adviser or Research Analyst, and its output is not investment
          advice or a research report under SEBI regulations.</li>
        <li>Verdicts, scores, trade plans, model probabilities, pattern signals, news summaries and sentiment are produced
          automatically by software from third-party data (NSE, Yahoo Finance, CNBC, CNBC-TV18). They can be delayed, incomplete
          or wrong. Past performance and back-tested accuracy do not guarantee future results.</li>
        <li>FII/DII figures are NSE&apos;s provisional data; participant-wise positions describe the previous session and are not a
          forecast.</li>
        <li>You are solely responsible for your investment decisions and any losses. Consult a SEBI-registered investment adviser
          before investing, and only trade with money you can afford to lose.</li>
      </ul>
      <div className="risk-box">
        <b>Risk disclosures on derivatives</b>
        <ul>
          <li>9 out of 10 individual traders in equity Futures and Options Segment, incurred net losses.</li>
          <li>On an average, loss makers registered net trading loss close to ₹ 50,000.</li>
          <li>Over and above the net trading losses incurred, loss makers expended an additional 28% of net trading losses as
            transaction costs.</li>
          <li>Those making net trading profits, incurred between 15% to 50% of such profits as transaction cost.</li>
        </ul>
        <span className="tiny muted">Source: SEBI study dated January 25, 2023 on “Analysis of Profit and Loss of Individual Traders
          dealing in equity Futures and Options (F&amp;O) Segment”, based on FY 2021-22 data.</span>
      </div>
      <p className="tiny muted">Headlines and links belong to their publishers. Market data is used for personal, non-commercial study.</p>
    </>
  )
}

// Shown every time the app is opened (per browser session); must be acknowledged before using the app.
export function DisclaimerModal({ open, onAccept, reread = false }) {
  const btn = useRef(null)
  useEffect(() => { if (open) btn.current?.focus() }, [open])
  if (!open) return null
  return (
    <div className="modal-back" role="dialog" aria-modal="true" aria-labelledby="disc-title">
      <div className="modal disclaimer-modal">
        <div className="disc-badge">Educational use only</div>
        <h2 id="disc-title">Before you continue</h2>
        <div className="disc-body"><DisclaimerText /></div>
        <div className="modal-actions">
          <button ref={btn} className="primary" onClick={onAccept}>
            {reread ? 'Close' : 'I understand — this is for education only'}
          </button>
        </div>
      </div>
    </div>
  )
}

export function HeaderNotice({ onOpen }) {
  return (
    <div className="header-notice" role="note">
      <span aria-hidden="true">⚠</span>
      <span>{SHORT_NOTICE}.</span>
      <button className="link tiny" onClick={onOpen}>Read disclaimer</button>
    </div>
  )
}

export function Footer({ onOpen }) {
  return (
    <footer className="app-footer">
      <p><b>For educational purposes only — not investment advice.</b> This app is not a SEBI-registered investment adviser or research
        analyst. Analyses and predictions are generated automatically and can be wrong. 9 out of 10 individual traders in equity
        F&amp;O incurred net losses (SEBI study, Jan 2023). Consult a SEBI-registered adviser before investing.{' '}
        <button className="link tiny" onClick={onOpen}>Full disclaimer</button></p>
      <p className="tiny muted">Data: NSE India, Yahoo Finance, CNBC, CNBC-TV18. Headlines belong to their publishers.</p>
    </footer>
  )
}
