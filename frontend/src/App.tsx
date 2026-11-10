import { useRef, useState } from 'react'
import { check, demo, extract } from './api/client'
import { ApiError, errorMessage, isFileError } from './api/errors'
import type { CheckRequest, DemoScenario, Mode, Report } from './api/types'
import { Header } from './components/Header'
import { ErrorScreen } from './screens/ErrorScreen'
import type { ErrorPhase } from './screens/ErrorScreen'
import { ProgressScreen } from './screens/ProgressScreen'
import type { ProgressPhase } from './screens/ProgressScreen'
import { ReportScreen } from './screens/ReportScreen'
import { ReviewScreen } from './screens/ReviewScreen'
import { StartScreen } from './screens/StartScreen'
import { UploadScreen } from './screens/UploadScreen'
import { emptyUploadDraft, manualFromDraft } from './state/upload'
import type { UploadDraft } from './state/upload'

// S1 시작 → S2 업로드 → S3 분석 중 → S4 내용 확인·수정 → S5 리포트 (PRD 4.1)
type View =
  | { name: 'start' }
  | { name: 'upload' }
  | { name: 'progress'; phase: ProgressPhase; startedAt: number; hasContract: boolean; source: Mode }
  | { name: 'error'; phase: ErrorPhase; message: string; code: string | null }
  | { name: 'review' }
  | { name: 'report' }

/** S3: 90초가 지나면 멈추고 오류 화면을 보여준다 (PRD 4.2 S3) */
const TIMEOUT_MS = 90_000
const TIMEOUT_MESSAGE = '90초 안에 끝나지 않아 멈췄어요. 잠시 후 다시 시도하거나 예시 결과를 확인하세요.'
/** /api/check가 이보다 빨리 끝나면 S3를 거치지 않고 바로 리포트를 보여준다 (화면 깜빡임 방지) */
const CHECK_PROGRESS_DELAY_MS = 400

interface Task {
  signal: AbortSignal
  isCurrent: () => boolean
  timedOut: () => boolean
  finish: () => void
}

export default function App() {
  const [view, setView] = useState<View>({ name: 'start' })
  const [upload, setUpload] = useState<UploadDraft>(emptyUploadDraft)
  const [request, setRequest] = useState<CheckRequest | null>(null)
  const [report, setReport] = useState<Report | null>(null)
  const [checking, setChecking] = useState(false)
  const [demoLoading, setDemoLoading] = useState<DemoScenario | null>(null)
  const [lastDemo, setLastDemo] = useState<DemoScenario>('C')
  // [빠진 내용 채우기]로 S4에 갈 때: 확인하지 못한 규칙 ID (S4가 관련된 빈 칸으로 이동한다)
  const [reviewFocus, setReviewFocus] = useState<string[] | null>(null)

  // 지금 진행 중인 요청. 새 요청을 시작하거나 취소하면 이전 요청의 결과는 버린다.
  const running = useRef<{ id: number; controller: AbortController | null }>({ id: 0, controller: null })

  function cancelRunning() {
    running.current.id += 1
    running.current.controller?.abort()
    running.current.controller = null
  }

  function beginTask(): Task {
    cancelRunning()
    setReviewFocus(null)
    const id = running.current.id
    const controller = new AbortController()
    running.current.controller = controller
    let timedOut = false
    const timer = window.setTimeout(() => {
      timedOut = true
      controller.abort()
    }, TIMEOUT_MS)
    return {
      signal: controller.signal,
      isCurrent: () => running.current.id === id,
      timedOut: () => timedOut,
      finish: () => {
        window.clearTimeout(timer)
        if (running.current.controller === controller) running.current.controller = null
      },
    }
  }

  function showError(phase: ErrorPhase, task: Task, err: unknown) {
    const timedOut = task.timedOut()
    setView({
      name: 'error',
      phase,
      message: timedOut ? TIMEOUT_MESSAGE : errorMessage(err),
      code: timedOut ? 'TIMEOUT' : err instanceof ApiError ? err.code : null,
    })
  }

  /** S2 → S3 → S4: 서류를 보내서 읽은 값을 받는다 */
  async function runExtract() {
    const registry = upload.registry
    if (!registry) return
    const task = beginTask()
    const manual = manualFromDraft(upload.manual)
    setView({
      name: 'progress',
      phase: 'extract',
      startedAt: Date.now(),
      hasContract: upload.contract !== null,
      source: 'live',
    })
    try {
      const res = await extract(registry, upload.contract, task.signal)
      if (!task.isCurrent()) return
      setRequest({
        registry: res.registry,
        contract: res.contract,
        manual,
        building: null,
        market: null,
        today: null,
        mode: 'live',
      })
      setReport(null)
      setView({ name: 'review' })
    } catch (err) {
      if (task.isCurrent()) showError('extract', task, err)
    } finally {
      task.finish()
    }
  }

  /** S4 → (S3) → S5: 고친 값으로 위험 신호를 검사한다. AI는 다시 부르지 않는다 (PRD F4) */
  async function runCheck(req: CheckRequest) {
    const task = beginTask()
    setRequest(req)
    setChecking(true)
    const startedAt = Date.now()
    const showProgress = window.setTimeout(() => {
      if (!task.isCurrent()) return
      setView({
        name: 'progress',
        phase: 'check',
        startedAt,
        hasContract: req.contract !== null,
        source: req.mode,
      })
    }, CHECK_PROGRESS_DELAY_MS)
    try {
      const result = await check(req, task.signal)
      if (!task.isCurrent()) return
      setReport(result)
      setView({ name: 'report' })
    } catch (err) {
      if (task.isCurrent()) showError('check', task, err)
    } finally {
      window.clearTimeout(showProgress)
      task.finish()
      if (task.isCurrent()) setChecking(false)
    }
  }

  /** S1 → S4: 데모 시나리오의 /api/check 입력을 불러온다 (today, mode, building, market 포함) */
  async function loadDemo(scenario: DemoScenario) {
    const task = beginTask()
    setDemoLoading(scenario)
    setLastDemo(scenario)
    try {
      const req = await demo(scenario, task.signal)
      if (!task.isCurrent()) return
      setRequest(req)
      setReport(null)
      setView({ name: 'review' })
    } catch (err) {
      if (task.isCurrent()) showError('demo', task, err)
    } finally {
      task.finish()
      setDemoLoading((current) => (current === scenario ? null : current))
    }
  }

  function goHome() {
    cancelRunning()
    setReviewFocus(null)
    setChecking(false)
    setDemoLoading(null)
    setUpload(emptyUploadDraft())
    setRequest(null)
    setReport(null)
    setView({ name: 'start' })
  }

  function cancelProgress(phase: ProgressPhase) {
    cancelRunning()
    setChecking(false)
    setView(phase === 'extract' ? { name: 'upload' } : { name: 'review' })
  }

  const demoMarker =
    view.name === 'report'
      ? report?.mode === 'demo'
      : request?.mode === 'demo' &&
        (view.name === 'review' ||
          (view.name === 'progress' && view.phase === 'check') ||
          (view.name === 'error' && view.phase === 'check'))

  let screen
  switch (view.name) {
    case 'start':
      screen = (
        <StartScreen
          onUpload={() => setView({ name: 'upload' })}
          onDemo={loadDemo}
          demoLoading={demoLoading}
        />
      )
      break
    case 'upload':
      screen = (
        <UploadScreen draft={upload} setDraft={setUpload} onSubmit={runExtract} onHome={goHome} />
      )
      break
    case 'progress':
      screen = (
        <ProgressScreen
          key={`${view.phase}-${view.startedAt}`}
          phase={view.phase}
          startedAt={view.startedAt}
          hasContract={view.hasContract}
          source={view.source}
          onCancel={() => cancelProgress(view.phase)}
        />
      )
      break
    case 'error': {
      const { phase } = view
      screen = (
        <ErrorScreen
          key={`${phase}-${view.message}`}
          phase={phase}
          message={view.message}
          code={view.code}
          fileError={isFileError(view.code)}
          onRetry={() => {
            if (phase === 'extract') void runExtract()
            else if (phase === 'check' && request) void runCheck(request)
            else void loadDemo(lastDemo)
          }}
          onBack={() => {
            if (phase === 'extract') setView({ name: 'upload' })
            else if (phase === 'check' && request) setView({ name: 'review' })
            else goHome()
          }}
          onDemo={loadDemo}
          demoLoading={demoLoading}
        />
      )
      break
    }
    case 'review':
      screen = request ? (
        <ReviewScreen
          request={request}
          checking={checking}
          focusRules={reviewFocus}
          onCheck={runCheck}
          onHome={goHome}
        />
      ) : null
      break
    case 'report':
      screen = report ? (
        <ReportScreen
          report={report}
          request={request}
          onEdit={() => {
            setReviewFocus(null)
            setView({ name: 'review' })
          }}
          onFillMissing={(unknownRuleIds) => {
            setReviewFocus(unknownRuleIds)
            setView({ name: 'review' })
          }}
          onHome={goHome}
        />
      ) : null
      break
  }

  return (
    <>
      <Header demo={demoMarker} />
      <main className="page">{screen}</main>
    </>
  )
}
