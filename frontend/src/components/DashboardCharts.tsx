import { useEffect, useRef, useState, type ReactNode } from 'react'
import { BarChart3, Table2 } from 'lucide-react'
import { useApi } from '../lib/hooks'
import { Select } from './ui'

interface Week { week_start: string; processing: number; validator: number; sme: number; completed: number }
interface SourceRow { source_system: string; auto: number; resolved: number; missing: number }
interface ChartData { period: string; weeks: Week[]; sources: SourceRow[] }

type StageKey = 'processing' | 'validator' | 'sme' | 'completed'
type OutcomeKey = 'auto' | 'resolved' | 'missing'

// Workflow stages are ordered, so they use one hue light -> dark (darker = further along).
const STAGES: { key: StageKey; label: string; color: string }[] = [
  { key: 'processing', label: 'Processing', color: 'var(--viz-stage-1)' },
  { key: 'validator', label: 'With validator', color: 'var(--viz-stage-2)' },
  { key: 'sme', label: 'With SME', color: 'var(--viz-stage-3)' },
  { key: 'completed', label: 'Completed', color: 'var(--viz-stage-4)' },
]
const OUTCOMES: { key: OutcomeKey; label: string; short: string; color: string }[] = [
  { key: 'auto', label: 'Retrieved automatically', short: 'Automatic', color: 'var(--viz-auto)' },
  { key: 'resolved', label: 'Resolved by validator', short: 'By validator', color: 'var(--viz-resolved)' },
  { key: 'missing', label: 'Still missing', short: 'Missing', color: 'var(--viz-missing)' },
]
const PERIODS = [
  { value: 'last_30', label: 'Last 30 days' },
  { value: 'last_90', label: 'Last 90 days' },
  { value: 'all', label: 'All time' },
]
const GAP = 2 // surface gap between touching segments
const MAX_BAR = 24

const weekTotal = (w: Week) => STAGES.reduce((n, s) => n + w[s.key], 0)
const srcTotal = (r: SourceRow) => r.auto + r.resolved + r.missing
const pct = (n: number, d: number) => (d ? Math.round((100 * n) / d) : 0)
const fmtWeek = (iso: string) => new Date(`${iso}T00:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

/** Clean y-axis: a max and step so there are at most 5 intervals of 1/2/5 x 10^n. */
function niceScale(max: number): { top: number; step: number } {
  if (max <= 0) return { top: 4, step: 1 }
  const raw = max / 4
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 5, 10].map((m) => m * mag).find((s) => s >= raw && Number.isInteger(s)) ?? Math.ceil(raw)
  return { top: Math.ceil(max / step) * step, step }
}

function useWidth<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T>(null)
  const [w, setW] = useState(0)
  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([e]) => setW(Math.floor(e.contentRect.width)))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}

/** Rect with only the data end rounded (top for columns, right for bars); square at the baseline. */
function endRounded(x: number, y: number, w: number, h: number, end: 'top' | 'right', rounded: boolean) {
  const r = rounded ? Math.min(4, w / 2, h) : 0
  if (end === 'top') {
    return `M${x},${y + h} V${y + r} Q${x},${y} ${x + r},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h} Z`
  }
  return `M${x},${y} H${x + w - r} Q${x + w},${y} ${x + w},${y + r} V${y + h - r} Q${x + w},${y + h} ${x + w - r},${y + h} H${x} Z`
}

function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="viz-legend">
      {items.map((i) => (
        <span key={i.label} className="viz-legend-item"><span className="viz-swatch" style={{ background: i.color }} />{i.label}</span>
      ))}
    </div>
  )
}

function Tooltip({ x, y, title, rows, total, side = 'above' }: {
  x: number; y: number; title: string; rows: { label: string; color: string; value: number }[]; total: string
  side?: 'above' | 'left' | 'right'
}) {
  return (
    <div className={`viz-tooltip side-${side}`} style={{ left: x, top: y }} role="status">
      <div className="viz-tooltip-title">{title}</div>
      {rows.map((r) => (
        <div key={r.label} className="viz-tooltip-row">
          <span className="viz-linekey" style={{ background: r.color }} />
          <strong>{r.value}</strong>
          <span>{r.label}</span>
        </div>
      ))}
      <div className="viz-tooltip-total">{total}</div>
    </div>
  )
}

function ChartCard({ title, sub, figure, figureLabel, asTable, onToggle, children }: {
  title: string; sub: string; figure: string; figureLabel: string; asTable: boolean; onToggle: () => void; children: ReactNode
}) {
  return (
    <div className="card viz-card">
      <div className="viz-head">
        <div>
          <div className="card-title">{title}</div>
          <div className="viz-sub">{sub}</div>
        </div>
        <div className="viz-head-right">
          <div className="viz-figure"><span>{figure}</span><small>{figureLabel}</small></div>
          <button className="viz-toggle" onClick={onToggle} aria-pressed={asTable}
                  title={asTable ? 'Show chart' : 'Show as table'}>
            {asTable ? <BarChart3 size={15} /> : <Table2 size={15} />} {asTable ? 'Chart' : 'Table'}
          </button>
        </div>
      </div>
      {children}
    </div>
  )
}

// ---- Chart 1: weekly intake by current workflow stage (stacked columns) -------------------------

function PipelineChart({ weeks }: { weeks: Week[] }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const H = 250, M = { l: 34, r: 8, t: 22, b: 28 }
  const plotW = Math.max(0, width - M.l - M.r), plotH = H - M.t - M.b
  const totals = weeks.map(weekTotal)
  const { top, step } = niceScale(Math.max(0, ...totals))
  const band = weeks.length ? plotW / weeks.length : 0
  const barW = Math.min(MAX_BAR, band * 0.55)
  const y = (v: number) => M.t + plotH - (v / top) * plotH
  const peak = totals.indexOf(Math.max(...totals))
  const last = weeks.length - 1
  const labelEvery = weeks.length > 10 ? 2 : 1

  return (
    <div className="viz-plot" ref={ref}>
      {width > 0 && (
        <svg width={width} height={H} role="img" aria-label="Requests created per week, stacked by current workflow stage">
          {Array.from({ length: top / step + 1 }, (_, i) => i * step).map((t) => (
            <g key={t}>
              <line x1={M.l} x2={width - M.r} y1={y(t)} y2={y(t)} className={t === 0 ? 'viz-baseline' : 'viz-grid'} />
              <text x={M.l - 8} y={y(t)} dy="0.32em" textAnchor="end" className="viz-tick">{t}</text>
            </g>
          ))}
          {weeks.map((w, i) => {
            const cx = M.l + band * i + band / 2
            let acc = 0
            const segs = STAGES.filter((s) => w[s.key] > 0)
            return (
              <g key={w.week_start} opacity={hover === null || hover === i ? 1 : 0.45} className="viz-col">
                {segs.map((s, j) => {
                  const y0 = y(acc), y1 = y(acc + w[s.key])
                  acc += w[s.key]
                  const isTop = j === segs.length - 1
                  const h = Math.max(1, y0 - y1 - (j > 0 ? GAP : 0))
                  return <path key={s.key} d={endRounded(cx - barW / 2, y0 - (j > 0 ? GAP : 0) - h, barW, h, 'top', isTop)} fill={s.color} />
                })}
                {totals[i] > 0 && (i === peak || i === last) && (
                  <text x={cx} y={y(totals[i]) - 7} textAnchor="middle" className="viz-cap">{totals[i]}</text>
                )}
                {(last - i) % labelEvery === 0 && (
                  <text x={cx} y={H - 8} textAnchor="middle" className="viz-tick">{fmtWeek(w.week_start)}</text>
                )}
                <rect x={M.l + band * i} y={M.t} width={band} height={plotH} fill="transparent" tabIndex={0}
                      aria-label={`Week of ${fmtWeek(w.week_start)}: ${totals[i]} requests`}
                      onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)}
                      onFocus={() => setHover(i)} onBlur={() => setHover(null)} className="viz-hit" />
              </g>
            )
          })}
        </svg>
      )}
      {hover !== null && weeks[hover] && (
        <Tooltip side={M.l + band * hover + band / 2 > width / 2 ? 'left' : 'right'}
                 x={M.l + band * hover + band / 2 + (M.l + band * hover + band / 2 > width / 2 ? -1 : 1) * (barW / 2 + 10)}
                 y={M.t + plotH / 2}
                 title={`Week of ${fmtWeek(weeks[hover].week_start)}`}
                 rows={[...STAGES].reverse().map((s) => ({ label: s.label, color: s.color, value: weeks[hover][s.key] }))}
                 total={`${totals[hover]} request${totals[hover] === 1 ? '' : 's'} created`} />
      )}
    </div>
  )
}

// ---- Chart 2: evidence outcome by source system (stacked horizontal bars) ---------------------------

function SourceChart({ sources }: { sources: SourceRow[] }) {
  const [ref, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const ROW = 30, LABEL = 64, TIP = 92, BAR = 16
  const H = sources.length * ROW + 4
  const plotW = Math.max(0, width - LABEL - TIP)
  const max = Math.max(1, ...sources.map(srcTotal))

  return (
    <div className="viz-plot" ref={ref}>
      {width > 0 && (
        <svg width={width} height={H} role="img" aria-label="Evidence items per source system by retrieval outcome">
          <line x1={LABEL} x2={LABEL} y1={0} y2={H} className="viz-baseline" />
          {sources.map((r, i) => {
            const yc = i * ROW + ROW / 2
            const total = srcTotal(r)
            let x = LABEL
            const segs = OUTCOMES.filter((o) => r[o.key] > 0)
            return (
              <g key={r.source_system} opacity={hover === null || hover === i ? 1 : 0.45}>
                <text x={LABEL - 10} y={yc} dy="0.32em" textAnchor="end" className="viz-cat">{r.source_system}</text>
                {segs.map((o, j) => {
                  const w = Math.max(1, (r[o.key] / max) * plotW - (j < segs.length - 1 ? GAP : 0))
                  const d = endRounded(x, yc - BAR / 2, w, BAR, 'right', j === segs.length - 1)
                  x += w + (j < segs.length - 1 ? GAP : 0)
                  return <path key={o.key} d={d} fill={o.color} />
                })}
                <text x={x + 8} y={yc} dy="0.32em" className="viz-cap">
                  {total} <tspan className="viz-tick">· {pct(r.auto, total)}% auto</tspan>
                </text>
                <rect x={0} y={i * ROW} width={width} height={ROW} fill="transparent" tabIndex={0} className="viz-hit"
                      aria-label={`${r.source_system}: ${r.auto} retrieved automatically, ${r.resolved} resolved by validator, ${r.missing} missing`}
                      onPointerEnter={() => setHover(i)} onPointerLeave={() => setHover(null)}
                      onFocus={() => setHover(i)} onBlur={() => setHover(null)} />
              </g>
            )
          })}
        </svg>
      )}
      {hover !== null && sources[hover] && (
        <Tooltip x={Math.min(LABEL + (srcTotal(sources[hover]) / max) * plotW / 2 + 40, width - 100)} y={hover * ROW + 2}
                 title={sources[hover].source_system}
                 rows={OUTCOMES.map((o) => ({ label: o.label, color: o.color, value: sources[hover][o.key] }))}
                 total={`${srcTotal(sources[hover])} evidence items · ${pct(sources[hover].auto, srcTotal(sources[hover]))}% automated`} />
      )}
    </div>
  )
}

// ---- Dashboard section --------------------------------------------------------------------------

/** Auditor dashboard insights: replaces the request table (which lives on the Requests page). */
export default function DashboardCharts() {
  const [period, setPeriod] = useState('last_30')
  const [tables, setTables] = useState({ pipeline: false, sources: false })
  const { data, loading } = useApi<ChartData>(`/api/dashboard/charts?period=${period}`, { poll: 15000 })
  const weeks = data?.weeks ?? []
  const sources = data?.sources ?? []
  const created = weeks.reduce((n, w) => n + weekTotal(w), 0)
  const completed = weeks.reduce((n, w) => n + w.completed, 0)
  const items = sources.reduce((n, r) => n + srcTotal(r), 0)
  const auto = sources.reduce((n, r) => n + r.auto, 0)
  const toggle = (k: keyof typeof tables) => setTables((t) => ({ ...t, [k]: !t[k] }))

  return (
    <section className={`viz-section${loading && data ? ' is-refetching' : ''}`} aria-label="Portfolio insights">
      <div className="viz-filters">
        <Select label="Period" value={period} onChange={setPeriod} options={PERIODS} />
      </div>
      <div className="viz-cards">
        <ChartCard title="Request pipeline" figure={`${pct(completed, created)}%`} figureLabel="completed"
                   sub={`${created} request${created === 1 ? '' : 's'} created, by week and where each one is now`}
                   asTable={tables.pipeline} onToggle={() => toggle('pipeline')}>
          <Legend items={STAGES} />
          {!created ? <div className="empty">No requests created in this period.</div> : tables.pipeline ? (
            <div className="viz-table-wrap"><table className="grid viz-table">
              <thead><tr><th>Week of</th>{STAGES.map((s) => <th key={s.key} className="right">{s.label}</th>)}<th className="right">Total</th></tr></thead>
              <tbody>{weeks.map((w) => (
                <tr key={w.week_start}><td>{fmtWeek(w.week_start)}</td>{STAGES.map((s) => <td key={s.key} className="right">{w[s.key]}</td>)}<td className="right"><strong>{weekTotal(w)}</strong></td></tr>
              ))}</tbody>
            </table></div>
          ) : <PipelineChart weeks={weeks} />}
        </ChartCard>

        <ChartCard title="Evidence retrieval by source system" figure={`${pct(auto, items)}%`} figureLabel="automated"
                   sub={`${auto} of ${items} evidence items retrieved automatically through MCP`}
                   asTable={tables.sources} onToggle={() => toggle('sources')}>
          <Legend items={OUTCOMES} />
          {!items ? <div className="empty">No evidence retrieved in this period.</div> : tables.sources ? (
            <div className="viz-table-wrap"><table className="grid viz-table">
              <thead><tr><th>Source</th>{OUTCOMES.map((o) => <th key={o.key} className="right">{o.short}</th>)}<th className="right">Auto %</th></tr></thead>
              <tbody>{sources.map((r) => (
                <tr key={r.source_system}><td>{r.source_system}</td>{OUTCOMES.map((o) => <td key={o.key} className="right">{r[o.key]}</td>)}<td className="right"><strong>{pct(r.auto, srcTotal(r))}%</strong></td></tr>
              ))}</tbody>
            </table></div>
          ) : <SourceChart sources={sources} />}
        </ChartCard>
      </div>
    </section>
  )
}
