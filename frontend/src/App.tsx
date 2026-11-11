import { useRef, useState } from 'react'
import { check, demo, demoRecheck, extract, recheck } from './api/client'
import { ApiError, errorMessage, isFileError } from './api/errors'
import type {
  CheckRequest,
  DemoScenario,
  Mode,
  RecheckReport,
  RecheckRequest,
  Report,
} from './api/types'
import { Header } from './components/Header'
import { ErrorScreen } from './screens/ErrorScreen'
import type { ErrorPhase } from './screens/ErrorScreen'
import { ProgressScreen } from './screens/ProgressScreen'
import type { ProgressPhase } from './screens/ProgressScreen'
import { RecheckReportScreen } from './screens/RecheckReportScreen'
import { RecheckConfirmScreen, RecheckUploadScreen } from './screens/RecheckScreen'
import { ReportScreen } from './screens/ReportScreen'
import { ReviewScreen } from './screens/ReviewScreen'
import { StartScreen } from './screens/StartScreen'
import { UploadScreen } from './screens/UploadScreen'
import { emptyRecheckUpload } from './state/recheck'
import type { RecheckCarry, RecheckUpload } from './state/recheck'
import { emptyUploadDraft, manualFromDraft } from './state/upload'
import type { UploadDraft } from './state/upload'

// S1 시작 → S2 업로드 → S3 분석 중 → S4 내용 확인·수정 → S5 리포트
// S6 계약 후 재확인(올리기 → 날짜 확인) → S3 → S7 계약 후 재확인서
type View =
  | { name: 'recheck' }
  | { name: 'recheck-report' }
  | { name: 'start' }
  | { name: 'upload' }
  | { name: 'progress'; phase: ProgressPhase; startedAt: number; hasContract: boolean; source: Mode }
  | { name: 'error'; phase: ErrorPhase; message: string; code: string | null }
  | { name: 'review' }
  | { name: 'report' }

/** S3: 90초가 지나면 멈추고 오류 화면을 보여준다 */
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

  // 계약 후 재확인. 아무것도 저장하지 않는다 (localStorage도 쓰지 않는다). 이 화면 흐름의 상태로만 잇는다.
  const [recheckCarry, setRecheckCarry] = useState<RecheckCarry | null>(null)
  const [recheckUpload, setRecheckUpload] = useState<RecheckUpload>(emptyRecheckUpload)
  /** S6 두 번째 단계(날짜 확인)에 보여줄 재확인 요청. null이면 올리기 단계 */
  const [recheckDraft, setRecheckDraft] = useState<RecheckRequest | null>(null)
  const [recheckReport, setRecheckReport] = useState<RecheckReport | null>(null)
  const [recheckDemoLoading, setRecheckDemoLoading] = useState(false)

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

  /** S4 → (S3) → S5: 고친 값으로 위험 신호를 검사한다. AI는 다시 부르지 않는다 */
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

  /** S6 열기. carry가 있으면 그 계약서를 그대로 쓰고 등기부만 새로 올린다 */
  function openRecheck(carry: RecheckCarry | null) {
    cancelRunning()
    setChecking(false)
    setRecheckCarry(carry)
    setRecheckUpload(emptyRecheckUpload())
    setRecheckDraft(null)
    setView({ name: 'recheck' })
  }

  /** S6 올리기 → S3 → S6 날짜 확인 */
  async function runRecheckExtract() {
    const registry = recheckUpload.registry
    const contractFile = recheckCarry ? null : recheckUpload.contract
    if (!registry || (!recheckCarry && !contractFile)) return
    const task = beginTask()
    setView({
      name: 'progress',
      phase: 'recheck-extract',
      startedAt: Date.now(),
      hasContract: contractFile !== null,
      source: 'live',
    })
    try {
      const res = await extract(registry, contractFile, task.signal)
      if (!task.isCurrent()) return
      const contract = recheckCarry?.contract ?? res.contract
      if (!contract) {
        throw new ApiError('계약서를 읽지 못했어요. 계약서 사진이나 PDF를 다시 올려 주세요.', 'NOT_CONTRACT')
      }
      setRecheckDraft({
        registry: res.registry,
        contract,
        baseline_viewed_at: recheckCarry?.baselineViewedAt ?? null,
        today: null,
        mode: 'live',
      })
      setView({ name: 'recheck' })
    } catch (err) {
      if (task.isCurrent()) showError('recheck-extract', task, err)
    } finally {
      task.finish()
    }
  }

  /** S6 날짜 확인 → (S3) → S7 */
  async function runRecheck(req: RecheckRequest) {
    const task = beginTask()
    setRecheckDraft(req)
    setChecking(true)
    const startedAt = Date.now()
    const showProgress = window.setTimeout(() => {
      if (!task.isCurrent()) return
      setView({ name: 'progress', phase: 'recheck', startedAt, hasContract: true, source: req.mode })
    }, CHECK_PROGRESS_DELAY_MS)
    try {
      const result = await recheck(req, task.signal)
      if (!task.isCurrent()) return
      setRecheckReport(result)
      setView({ name: 'recheck-report' })
    } catch (err) {
      if (task.isCurrent()) showError('recheck', task, err)
    } finally {
      window.clearTimeout(showProgress)
      task.finish()
      if (task.isCurrent()) setChecking(false)
    }
  }

  /** S1 예시 "A 집, 잔금 이틀 전 근저당이 생긴 경우" → S7 (예시의 today·mode를 그대로 쓴다) */
  async function loadRecheckDemo() {
    const task = beginTask()
    setRecheckDemoLoading(true)
    try {
      const req = await demoRecheck(task.signal)
      if (!task.isCurrent()) return
      const result = await recheck(req, task.signal)
      if (!task.isCurrent()) return
      setRecheckCarry({ contract: req.contract, baselineViewedAt: req.baseline_viewed_at })
      setRecheckDraft(req)
      setRecheckReport(result)
      setView({ name: 'recheck-report' })
    } catch (err) {
      if (task.isCurrent()) showError('recheck-demo', task, err)
    } finally {
      task.finish()
      setRecheckDemoLoading(false)
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
    setRecheckCarry(null)
    setRecheckUpload(emptyRecheckUpload())
    setRecheckDraft(null)
    setRecheckReport(null)
    setView({ name: 'start' })
  }

  function cancelProgress(phase: ProgressPhase) {
    cancelRunning()
    setChecking(false)
    if (phase === 'extract') setView({ name: 'upload' })
    else if (phase === 'check') setView({ name: 'review' })
    else if (phase === 'recheck-extract') {
      setRecheckDraft(null)
      setView({ name: 'recheck' })
    } else setView({ name: 'recheck' })
  }

  const demoMarker =
    view.name === 'recheck-report'
      ? recheckReport?.mode === 'demo'
      : view.name === 'progress' && view.phase === 'recheck'
        ? view.source === 'demo'
        : view.name === 'report'
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
          onRecheck={() => openRecheck(null)}
          onRecheckDemo={loadRecheckDemo}
          recheckDemoLoading={recheckDemoLoading}
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
            else if (phase === 'recheck-extract') void runRecheckExtract()
            else if (phase === 'recheck' && recheckDraft) void runRecheck(recheckDraft)
            else if (phase === 'recheck-demo') void loadRecheckDemo()
            else void loadDemo(lastDemo)
          }}
          onBack={() => {
            if (phase === 'extract') setView({ name: 'upload' })
            else if (phase === 'check' && request) setView({ name: 'review' })
            else if (phase === 'recheck-extract') {
              setRecheckDraft(null)
              setView({ name: 'recheck' })
            } else if (phase === 'recheck' && recheckDraft) setView({ name: 'recheck' })
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
          onRecheck={() =>
            openRecheck(
              request?.contract
                ? { contract: request.contract, baselineViewedAt: request.registry.viewed_at }
                : null,
            )
          }
          onHome={goHome}
        />
      ) : null
      break
    case 'recheck':
      screen = recheckDraft ? (
        <RecheckConfirmScreen
          key={recheckDraft.registry.viewed_at ?? 'confirm'}
          draft={recheckDraft}
          checking={checking}
          onRecheck={runRecheck}
          onReselect={() => setRecheckDraft(null)}
          onHome={goHome}
        />
      ) : (
        <RecheckUploadScreen
          carry={recheckCarry}
          upload={recheckUpload}
          setUpload={setRecheckUpload}
          onSubmit={runRecheckExtract}
          onHome={goHome}
        />
      )
      break
    case 'recheck-report':
      screen = recheckReport ? (
        <RecheckReportScreen
          report={recheckReport}
          onAgain={() => {
            const last = recheckDraft
            openRecheck(
              last ? { contract: last.contract, baselineViewedAt: last.baseline_viewed_at } : recheckCarry,
            )
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
