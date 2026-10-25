import { useEffect, useMemo, useState } from 'react'
import { ArrowRight, Bot, Check, ChevronRight, CircleAlert, Code2, Copy, FileCode2, Github, LockKeyhole, Play, Radar, ScanSearch, Shield, ShieldAlert, Sparkles, Terminal } from 'lucide-react'

type Analysis = { category: string; explanation: string; impact: string; risk: string; remediation: string; uncertainty: string }
type Fix = { original_code: string; corrected_code: string; explanation: string; confidence: string; verification: string }
type Finding = { id: string; title: string; severity: 'HIGH' | 'MEDIUM' | 'LOW'; filename: string; line: number; rule_id: string; snippet: string; explanation: string; analysis: Analysis | null; fix: Fix | null; ai_error: string | null }
type Event = { timestamp: string; agent: string; action: string; status: string; outcome: string }
type Scan = { id: string; source: string; state: string; events: Event[]; findings: Finding[]; metrics: { files_scanned: number; source_bytes: number }; error: string | null; summary: { total: number; by_severity: Record<string, number>; analyzed: number; fixes_proposed: number } }
type Health = { status: string; ollama: { available: boolean; model: string; error: string | null }; semgrep: boolean }

const STAGES = [
  { state: 'CLONING', name: 'Recon Agent', caption: 'Source isolation & inventory', icon: Radar },
  { state: 'SCANNING', name: 'Vulnerability Scanner', caption: 'Curated Semgrep rules', icon: ScanSearch },
  { state: 'ANALYZING', name: 'AI Analyst', caption: 'Qwen3 security reasoning', icon: Bot },
  { state: 'GENERATING_FIX', name: 'Remediation Agent', caption: 'Minimal code replacement', icon: Code2 },
]

function App() {
  const [showLiveNotice, setShowLiveNotice] = useState(() => window.location.hostname.endsWith('.vercel.app'))
  const [source, setSource] = useState('')
  const [scanId, setScanId] = useState<string | null>(null)
  const [scan, setScan] = useState<Scan | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    const load = () => fetch('/api/health').then(r => r.json()).then(setHealth).catch(() => setHealth(null))
    load()
    const timer = window.setInterval(load, 10000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    if (!scanId) return
    let active = true
    const load = async () => {
      try {
        const response = await fetch(`/api/scans/${scanId}`)
        if (!response.ok) throw new Error(`Scan status failed (${response.status})`)
        const data: Scan = await response.json()
        if (active) setScan(data)
      } catch (error) { if (active) setRequestError(String(error)) }
    }
    load()
    const timer = window.setInterval(load, 1200)
    return () => { active = false; clearInterval(timer) }
  }, [scanId])

  useEffect(() => { if (!selectedId && scan?.findings.length) setSelectedId(scan.findings[0].id) }, [scan, selectedId])
  const selected = scan?.findings.find(f => f.id === selectedId) ?? null
  const busy = submitting || (!!scanId && !scan) || (!!scan && !['COMPLETE', 'FAILED'].includes(scan.state))
  const activeStages = useMemo(() => new Set(scan?.events.filter(e => e.status === 'running').map(e => e.action.toUpperCase().replaceAll(' ', '_')) ?? []), [scan])

  async function start(value: string) {
    setSubmitting(true); setRequestError(null); setScan(null); setScanId(null); setSelectedId(null)
    try {
      const response = await fetch('/api/scans', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ source: value }) })
      const data = await response.json()
      if (!response.ok) throw new Error(data.detail ?? `Scan request failed (${response.status})`)
      setScanId(data.id)
    } catch (error) { setRequestError(error instanceof Error ? error.message : String(error)) }
    finally { setSubmitting(false) }
  }

  async function copyFix() {
    if (!selected?.fix) return
    await navigator.clipboard.writeText(selected.fix.corrected_code)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1800)
  }

  async function investigate() {
    if (!scanId || !selected) return
    setRequestError(null)
    try {
      const response = await fetch(`/api/scans/${scanId}/findings/${selected.id}/investigate`, { method: 'POST' })
      if (!response.ok) {
        const data = await response.json()
        throw new Error(data.detail ?? `Investigation failed (${response.status})`)
      }
    } catch (error) { setRequestError(error instanceof Error ? error.message : String(error)) }
  }

  return <>
    {showLiveNotice && <div className="live-notice-backdrop" role="presentation">
      <section className="live-notice-dialog" role="dialog" aria-modal="true" aria-labelledby="live-notice-title" aria-describedby="live-notice-copy">
        <div className="live-notice-icon"><Bot size={20}/></div>
        <p className="live-notice-kicker">LIVE UI PREVIEW</p>
        <h2 id="live-notice-title">Running this on your own machine?</h2>
        <p id="live-notice-copy">This is the live UI demo. To run scans and AI analysis, set up Ollama with the qwen3:4b model on your own laptop.</p>
        <button type="button" onClick={() => setShowLiveNotice(false)}>Continue to the demo <ArrowRight size={15}/></button>
      </section>
    </div>}
    <main className="breaksmith-shell">
    <section id="scan-console" className="breaksmith-console">
        <div className="console-heading"><div><p className="section-eyebrow">LIVE OPERATIONS</p><h2>Security scan console</h2><p>Run a repository through the real scanner and local model workflow.</p></div><span className={`state-badge ${scan?.state === 'FAILED' ? 'failed' : scan?.state === 'COMPLETE' ? 'done' : ''}`}><span className={`status-dot ${scan?.state === 'COMPLETE' ? 'is-online' : ''}`}/>{scan?.state ?? 'IDLE'}</span></div>

        <form className="scan-source" onSubmit={e => { e.preventDefault(); if (source.trim()) start(source.trim()) }}>
          <div className="source-label"><Github size={19}/><span>REPOSITORY SOURCE</span></div>
          <input aria-label="GitHub repository URL or allowed local directory" placeholder="https://github.com/owner/repository or local directory" value={source} onChange={e => setSource(e.target.value)} disabled={busy}/>
          <button type="submit" disabled={busy || !source.trim()}>{busy ? 'Scanning…' : 'Start security scan'} <ArrowRight size={15}/></button>
        </form>
        <div className="scan-shortcuts"><button type="button" disabled={busy} onClick={() => { setSource('demo'); start('demo') }}><Play size={13} fill="currentColor"/> Try demo repository</button><span>Public GitHub URL or allowed local directory · source code stays read only</span></div>
        {(requestError || scan?.error) && <div className="notice error"><CircleAlert size={18}/><div><strong>Operation failed</strong><p>{requestError || scan?.error}</p></div></div>}
        {health && (!health.ollama.available || !health.semgrep) && <div className="notice warning"><CircleAlert size={18}/><div><strong>Dependency check</strong><p>{!health.semgrep ? 'Semgrep CLI is unavailable. Install backend requirements. ' : ''}{health.ollama.error ? `Ollama: ${health.ollama.error}` : ''}</p></div></div>}
        <div className="dashboard-grid"><section className="panel workflow-panel"><div className="panel-heading"><div><div className="section-kicker">ORCHESTRATION</div><h2>Agent workflow</h2></div><span className={`state-badge ${scan?.state === 'FAILED' ? 'failed' : scan?.state === 'COMPLETE' ? 'done' : ''}`}><span className={`status-dot ${scan?.state === 'COMPLETE' ? 'is-online' : ''}`}/>{scan?.state ?? 'IDLE'}</span></div>
          <div className="workflow-list">{STAGES.map((step, index) => { const Icon = step.icon; const occurred = activeStages.has(step.state); const current = scan?.state === step.state; const lastResult = [...(scan?.events ?? [])].reverse().find(e => e.agent === step.name && (e.status === 'error' || e.status === 'complete')); const failed = lastResult?.status === 'error'; return <div className={`workflow-step ${occurred ? 'occurred' : ''} ${current ? 'current' : ''} ${failed ? 'failed' : ''}`} key={step.state}><div className="step-index">{occurred && !current && !failed ? <Check size={14}/> : String(index + 1).padStart(2, '0')}</div><div className="step-icon"><Icon size={17}/></div><div className="step-copy"><strong>{step.name}</strong><span>{step.caption}</span></div><span className="step-status">{current ? 'ACTIVE' : failed ? 'ERROR' : occurred ? 'DONE' : 'PENDING'}</span></div> })}</div>
          <div className="workflow-foot"><span className="live-indicator"><span className="status-dot"/> {busy ? 'PROCESSING LIVE EVENTS' : scan?.state === 'FAILED' ? 'LAST RUN FAILED' : scan ? 'LAST RUN COMPLETE' : 'AWAITING REPOSITORY'}</span><span>{scan?.events.length ?? 0} events</span></div>
        </section>
        <section className="panel telemetry-panel"><div className="panel-heading"><div><div className="section-kicker">LIVE TELEMETRY</div><h2>Activity stream</h2></div><Terminal size={19} className="muted-icon"/></div><div className="terminal-window"><div className="terminal-top"><span/><span/><span/><div>breaksmith / agent.log</div></div><div className="terminal-content">{scan?.events.length ? scan.events.map((e, i) => <div className="log-line" key={i}><span className="log-time">{new Date(e.timestamp).toLocaleTimeString()}</span><span className={`log-caret ${e.status}`}>›</span><span className="log-agent">{e.agent}</span><span className="log-body">{e.action}{e.outcome ? ` — ${e.outcome}` : ''}</span></div>) : <div className="terminal-empty"><span className="terminal-prompt">›</span> Waiting for a repository to scan<span className="cursor">_</span></div>}</div></div></section></div>
        <section className="metrics-row" aria-label="Scan summary"><Metric label="FILES SCANNED" value={scan?.metrics.files_scanned ?? 0} icon={<FileCode2 size={16}/>}/><Metric label="FINDINGS" value={scan?.summary.total ?? 0} icon={<ShieldAlert size={16}/>}/><Metric label="AI ANALYZED" value={scan?.summary.analyzed ?? 0} icon={<Sparkles size={16}/>}/><Metric label="FIXES PROPOSED" value={scan?.summary.fixes_proposed ?? 0} icon={<Code2 size={16}/>}/></section>
        <div className="findings-layout"><section className="panel findings-panel"><div className="panel-heading"><div><div className="section-kicker">SECURITY REPORT</div><h2>Findings <span className="heading-count">{scan?.summary.total ?? 0}</span></h2></div><span className="mini-meta">HIGH {scan?.summary.by_severity.HIGH ?? 0} · MED {scan?.summary.by_severity.MEDIUM ?? 0} · LOW {scan?.summary.by_severity.LOW ?? 0}</span></div><div className="findings-list">{scan?.findings.length ? scan.findings.map(f => <button className={`finding-row ${selectedId === f.id ? 'selected' : ''}`} key={f.id} onClick={() => setSelectedId(f.id)}><span className={`severity-mark ${f.severity.toLowerCase()}`}/><div className="finding-main"><strong>{f.title}</strong><span>{f.filename}:{f.line}</span></div><div className="finding-side"><span className={`severity-label ${f.severity.toLowerCase()}`}>{f.severity}</span><span className="finding-ai">{f.fix ? 'FIX READY' : f.analysis ? 'AI ANALYZED' : f.ai_error ? 'AI ERROR' : 'SCAN ONLY'}</span></div><ChevronRight size={15}/></button>) : <div className="empty-findings"><div className="empty-icon"><ScanSearch size={23}/></div><strong>{scan?.state === 'COMPLETE' ? 'No findings detected' : 'No findings yet'}</strong><p>{scan?.state === 'COMPLETE' ? 'The included rules found no matching patterns. This does not prove the repository is secure.' : 'Start a scan to see real Semgrep results here.'}</p></div>}</div></section>
          <section className="panel detail-panel"><div className="panel-heading"><div><div className="section-kicker">INVESTIGATION</div><h2>Finding detail</h2></div>{selected && <span className={`severity-label ${selected.severity.toLowerCase()}`}>{selected.severity}</span>}</div>{selected ? <div className="detail-content"><div className="detail-head"><strong>{selected.title}</strong><span><FileCode2 size={14}/>{selected.filename}:{selected.line}</span></div><div className="detail-section"><div className="detail-label">SCANNER EVIDENCE <span>{selected.rule_id}</span></div><pre className="code-block evidence"><code>{selected.snippet}</code></pre></div>
            {selected.analysis ? <div className="detail-section"><div className="detail-label">QWEN3 ANALYSIS <span className="ai-tag"><Sparkles size={12}/> LOCAL MODEL</span></div><p className="analysis-copy">{selected.analysis.explanation}</p><div className="analysis-grid"><div><span>CATEGORY</span><strong>{selected.analysis.category}</strong></div><div><span>RISK</span><strong>{selected.analysis.risk}</strong></div></div><p className="support-copy"><b>Impact</b> {selected.analysis.impact}</p><p className="support-copy"><b>Remediation</b> {selected.analysis.remediation}</p><p className="uncertainty">{selected.analysis.uncertainty}</p></div> : <div className="analysis-pending"><Bot size={17}/>{selected.ai_error ? selected.ai_error : busy ? 'AI analysis pending or in progress…' : 'This finding has scanner evidence only.'}</div>}
            {selected.fix ? <div className="detail-section fix-section"><div className="detail-label">PROPOSED CODE REPLACEMENT <button className="copy-button" onClick={copyFix}>{copied ? <Check size={13}/> : <Copy size={13}/>} {copied ? 'COPIED' : 'COPY FIX'}</button></div><div className="diff-label before">− ORIGINAL</div><pre className="code-block diff-before"><code>{selected.fix.original_code}</code></pre><div className="diff-label after">+ SUGGESTED</div><pre className="code-block diff-after"><code>{selected.fix.corrected_code}</code></pre><p className="support-copy">{selected.fix.explanation}</p><p className="uncertainty">Confidence: {selected.fix.confidence} · Verify: {selected.fix.verification}</p><div className="read-only-note"><LockKeyhole size={14}/> Suggestion only. Review before changing source.</div></div> : scan?.state === 'COMPLETE' && <button className="investigate-button" onClick={investigate}><Sparkles size={15}/> Analyze & propose fix <ArrowRight size={15}/></button>}
            </div> : <div className="detail-empty"><div className="detail-empty-icon"><Shield size={27}/></div><strong>Select a finding</strong><p>Scanner evidence, local AI reasoning, and code repairs will appear here.</p></div>}</section></div>
      </section>
    </main>
  </>
}

function Metric({ label, value, icon }: { label: string; value: number; icon: React.ReactNode }) { return <div className="metric"><div className="metric-top"><span>{label}</span>{icon}</div><div className="metric-value">{value.toString().padStart(2, '0')}<span className="metric-slash">/</span></div></div> }

export default App
