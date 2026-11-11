import { useEffect, useRef, useState } from 'react'
import {
  check,
  compare,
  demo,
  demoCompare,
  demoRecheck,
  extract,
  extractContract,
  recheck,
} from './api/client'
import { ApiError, errorMessage, isFileError } from './api/errors'
import type { ErrorDocument } from './api/errors'
import type {
  CheckRequest,
  CompareReport,
  CompareRequest,
  ContractExtract,
  DemoScenario,
  ISODateTime,
  Mode,
  RecheckReport,
  RecheckRequest,
  Report,
} from './api/types'
import { Header } from './components/Header'
import { CompareReportScreen } from './screens/CompareReportScreen'
import { CompareUploadScreen } from './screens/CompareUploadScreen'
import { ErrorScreen } from './screens/ErrorScreen'
import type { ErrorPhase } from './screens/ErrorScreen'
import { PrivacyScreen } from './screens/PrivacyScreen'
import { ProgressScreen } from './screens/ProgressScreen'
import type { ProgressPhase } from './screens/ProgressScreen'
import { RecheckReportScreen } from './screens/RecheckReportScreen'
import { RecheckConfirmScreen, RecheckUploadScreen } from './screens/RecheckScreen'
import { ReportScreen } from './screens/ReportScreen'
import { ReviewScreen } from './screens/ReviewScreen'
import { StartScreen } from './screens/StartScreen'
import { UploadScreen } from './screens/UploadScreen'
import { contractFileToSend, sentPick } from './state/contract'
import type { ContractPick } from './state/contract'
import { emptyRecheckUpload } from './state/recheck'
import type { RecheckCarry, RecheckUpload } from './state/recheck'
import { emptyUploadDraft, manualFromDraft } from './state/upload'
import type { UploadDraft } from './state/upload'

// S1 시작 → S2 업로드 → S3 분석 중 → S4 내용 확인·수정 → S5 리포트
// S6 계약 후 재확인(올리기 → 날짜 확인) → S3 → S7 계약 후 재확인서
// S5 → 수정된 계약서 올리기 → S3 → S8 수정 전·후 비교서 → S5(수정 후)
type View =
  | { name: 'start' }
  | { name: 'privacy' }
  | { name: 'upload' }
  | { name: 'progress'; phase: ProgressPhase; startedAt: number; hasContract: boolean; source: Mode }
  | {
      name: 'error'
      phase: ErrorPhase
      message: string
      code: string | null
      document: ErrorDocument | null
      /** 같은 오류가 다시 나도 화면을 새로 그려 알리도록 */
      at: number
    }
  | { name: 'review' }
  | { name: 'report' }
  | { name: 'recheck' }
  | { name: 'recheck-confirm' }
  | { name: 'recheck-report' }
  | { name: 'compare-upload' }
  | { name: 'compare-report' }

const START: View = { name: 'start' }

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

/** 화면을 다시 그릴 때 필요한 메모리의 결과들 (뒤로 가기로 돌아왔을 때 확인한다) */
interface Snapshot {
  request: CheckRequest | null
  report: Report | null
  recheckDraft: RecheckRequest | null
  recheckReport: RecheckReport | null
  compareReport: CompareReport | null
}

/**
 * 브라우저 기록 한 칸에 남기는 표시. 결과는 넣지 않고 화면 순서만 적는다.
 * idx는 이 탭에서 앱의 첫 칸부터 센 위치다 (새로 고침하면 첫 칸으로 돌아가서 다시 센다).
 */
interface HistoryMark {
  /** 페이지를 열 때마다 새로 정하는 값. 다르면 새로 고침 전의 기록이다 */
  app: string
  idx: number
}

/** 진행 중·오류 화면은 결과가 나오면 그 자리를 결과 화면이 대신한다 */
function isTransient(view: View): boolean {
  return view.name === 'progress' || view.name === 'error'
}

/** S3 [취소]로 돌아갈 화면 */
function progressOrigin(phase: ProgressPhase): View {
  if (phase === 'extract') return { name: 'upload' }
  if (phase === 'check') return { name: 'review' }
  if (phase === 'recheck-extract') return { name: 'recheck' }
  if (phase === 'recheck') return { name: 'recheck-confirm' }
  return { name: 'compare-upload' }
}

/** 오류 화면의 돌아가기 버튼이 갈 화면 */
function errorOrigin(phase: ErrorPhase): View {
  if (phase === 'compare') return { name: 'report' }
  if (phase === 'demo' || phase === 'recheck-demo' || phase === 'compare-demo') return START
  return progressOrigin(phase)
}

/** 그 화면에 필요한 결과가 메모리에 없으면 보여줄 수 있는 화면으로 바꾼다 */
function usable(view: View, s: Snapshot): View {
  switch (view.name) {
    case 'progress':
      return usable(progressOrigin(view.phase), s)
    case 'error':
      return usable(errorOrigin(view.phase), s)
    case 'review':
      return s.request ? view : START
    case 'report':
      return s.report ? view : START
    case 'recheck-confirm':
      return s.recheckDraft ? view : { name: 'recheck' }
    case 'recheck-report':
      return s.recheckReport ? view : START
    case 'compare-upload':
      return s.request && s.report ? view : START
    case 'compare-report':
      return s.compareReport ? view : START
    default:
      return view
  }
}

/** 예시 계약서는 실제 재확인에 이어 쓰지 않는다 (예시 계약서로 내 등기부를 확인하는 일이 없게) */
function liveCarry(
  contract: ContractExtract | null | undefined,
  baselineViewedAt: ISODateTime | null | undefined,
  mode: Mode | undefined,
): RecheckCarry | null {
  return contract && mode === 'live' ? { contract, baselineViewedAt: baselineViewedAt ?? null } : null
}

export default function App() {
  const [view, setView] = useState<View>(START)
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
  /** S6 두 번째 단계(날짜 확인)에 보여줄 재확인 요청 */
  const [recheckDraft, setRecheckDraft] = useState<RecheckRequest | null>(null)
  const [recheckReport, setRecheckReport] = useState<RecheckReport | null>(null)
  const [recheckDemoLoading, setRecheckDemoLoading] = useState(false)

  // 수정 전·후 비교. 수정 전 입력은 지금의 request(메모리)이고, 저장하지 않는다.
  const [compareContract, setCompareContract] = useState<ContractPick | null>(null)
  const [compareConsent, setCompareConsent] = useState(false)
  /** 비교 중인 요청 (다시 시도할 때 쓴다) */
  const [compareDraft, setCompareDraft] = useState<CompareRequest | null>(null)
  const [compareReport, setCompareReport] = useState<CompareReport | null>(null)
  /** 수정 후 검사 입력과 결과: [수정된 계약서로 검토서 보기]를 누르면 지금의 검토서가 된다 */
  const [compareAfter, setCompareAfter] = useState<{ request: CheckRequest; report: Report } | null>(null)
  const [compareDemoLoading, setCompareDemoLoading] = useState(false)

  // 지금 진행 중인 요청. 새 요청을 시작하거나 취소하면 이전 요청의 결과는 버린다.
  const running = useRef<{ id: number; controller: AbortController | null }>({ id: 0, controller: null })

  // 화면 기록: 브라우저 기록 한 칸마다 화면 하나. 결과는 App 상태(메모리)에만 있고 기록에는 순서만 남긴다.
  const [historyKey] = useState(() => Math.random().toString(36).slice(2))
  const nav = useRef<{ stack: View[]; idx: number; started: boolean }>({ stack: [START], idx: 0, started: false })
  const current: Snapshot = { request, report, recheckDraft, recheckReport, compareReport }

  /**
   * 화면을 바꾸고 브라우저 기록에 한 칸 남긴다.
   * 진행 중·오류 화면에서 바뀌거나 같은 화면이면 새 칸을 만들지 않고 그 칸을 바꾼다.
   */
  function show(next: View, how: 'auto' | 'replace' = 'auto') {
    const n = nav.current
    const now = n.stack[n.idx]
    if (how === 'replace' || isTransient(now) || now.name === next.name) {
      n.stack[n.idx] = next
    } else {
      n.stack.splice(n.idx + 1)
      n.stack.push(next)
      n.idx += 1
      window.history.pushState(mark(n.idx), '')
    }
    setView(next)
  }

  function cancelRunning() {
    running.current.id += 1
    running.current.controller?.abort()
    running.current.controller = null
  }

  /** 진행 중인 요청을 멈추고, 불러오는 중 표시를 모두 끈다 (화면을 떠날 때마다) */
  function stopRunning() {
    cancelRunning()
    setChecking(false)
    setDemoLoading(null)
    setRecheckDemoLoading(false)
    setCompareDemoLoading(false)
  }

  /** 사용자가 다른 화면으로 갈 때 */
  function go(next: View) {
    stopRunning()
    show(next)
  }

  /** 앞 화면으로 돌아간다. 기록의 바로 앞 칸이 그 화면이면 브라우저 기록도 한 칸 뒤로 간다 */
  function backTo(target: View) {
    stopRunning()
    const n = nav.current
    const prev = n.stack[n.idx - 1]
    if (prev && prev.name === target.name) {
      n.idx -= 1
      setView(usable(prev, current))
      window.history.back()
    } else {
      show(usable(target, current))
    }
  }

  function mark(idx: number): HistoryMark {
    return { app: historyKey, idx }
  }

  /** 브라우저 뒤로·앞으로: 진행 중인 요청을 멈추고 그 칸의 화면으로 간다 (앱 밖으로 나가지 않는다) */
  function onHistoryMove(raw: unknown) {
    const state = raw as Partial<HistoryMark> | null
    const n = nav.current
    stopRunning()
    if (state && state.app !== historyKey && typeof state.idx === 'number' && state.idx > 0) {
      // 새로 고침 전의 칸 (결과가 메모리에 없다): 보여주지 않고 앱의 첫 칸으로 건너뛴다
      window.history.go(-state.idx)
      return
    }
    if (!state || state.app !== historyKey || typeof state.idx !== 'number' || !n.stack[state.idx]) {
      // 앱의 첫 칸 (새로 고침 전의 첫 칸이나 모르는 기록): 처음 화면으로 삼는다
      n.stack = [START]
      n.idx = 0
      window.history.replaceState(mark(0), '')
      setView(START)
      return
    }
    n.idx = state.idx
    const target = usable(n.stack[n.idx], current)
    n.stack[n.idx] = target
    setView(target)
  }

  // 기록 이동 처리는 늘 최신 상태로 한다
  const historyMove = useRef(onHistoryMove)
  useEffect(() => {
    historyMove.current = onHistoryMove
  })
  useEffect(() => {
    const n = nav.current
    if (!n.started) {
      n.started = true
      const before = window.history.state as Partial<HistoryMark> | null
      if (before && typeof before.app === 'string' && typeof before.idx === 'number' && before.idx > 0) {
        // 새로 고침: 앞 칸들의 결과는 사라졌으므로 앱의 첫 칸으로 돌아간다.
        // 그러면 처음 화면에서 뒤로 한 번에 앱을 떠난다 (첫 칸에 도착하면 onHistoryMove가 처음 화면으로 삼는다)
        window.history.go(-before.idx)
      } else {
        window.history.replaceState({ app: historyKey, idx: n.idx } satisfies HistoryMark, '')
      }
    }
    const onPopState = (e: PopStateEvent) => historyMove.current(e.state)
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [historyKey])

  function beginTask(): Task {
    stopRunning()
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
    const apiError = !timedOut && err instanceof ApiError ? err : null
    show({
      name: 'error',
      phase,
      message: timedOut ? TIMEOUT_MESSAGE : errorMessage(err),
      code: timedOut ? 'TIMEOUT' : (apiError?.code ?? null),
      document: apiError?.document ?? null,
      at: Date.now(),
    })
  }

  /** S2 → S3 → S4: 서류를 보내서 읽은 값을 받는다 */
  async function runExtract() {
    const registry = upload.registry
    const pick = upload.contract
    if (!registry || !upload.consent) return
    const task = beginTask()
    const manual = manualFromDraft(upload.manual)
    show({
      name: 'progress',
      phase: 'extract',
      startedAt: Date.now(),
      hasContract: pick !== null,
      source: 'live',
    })
    try {
      // 계약서 사진은 가린 사진만 보낸다. 가리기 전 사진은 보내는 순간 버린다
      const contractFile = await contractFileToSend(pick)
      if (!task.isCurrent()) return
      if (pick && contractFile) {
        setUpload((d) => (d.contract === pick ? { ...d, contract: sentPick(pick, contractFile) } : d))
      }
      const res = await extract(registry, contractFile, task.signal)
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
      show({ name: 'review' })
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
      show({
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
      show({ name: 'report' })
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
      show({ name: 'review' })
    } catch (err) {
      if (task.isCurrent()) showError('demo', task, err)
    } finally {
      task.finish()
      if (task.isCurrent()) setDemoLoading(null)
    }
  }

  /** S6 열기. carry가 있으면 그 계약서를 그대로 쓰고 등기부만 새로 올린다 */
  function openRecheck(carry: RecheckCarry | null) {
    stopRunning()
    setRecheckCarry(carry)
    setRecheckUpload(emptyRecheckUpload())
    setRecheckDraft(null)
    show({ name: 'recheck' })
  }

  /** S6 올리기 → S3 → S6 날짜 확인 */
  async function runRecheckExtract() {
    const registry = recheckUpload.registry
    const carry = recheckCarry
    const pick = carry ? null : recheckUpload.contract
    if (!registry || (!carry && !pick) || !recheckUpload.consent) return
    const task = beginTask()
    show({
      name: 'progress',
      phase: 'recheck-extract',
      startedAt: Date.now(),
      hasContract: pick !== null,
      source: 'live',
    })
    try {
      const contractFile = await contractFileToSend(pick)
      if (!task.isCurrent()) return
      if (pick && contractFile) {
        setRecheckUpload((u) => (u.contract === pick ? { ...u, contract: sentPick(pick, contractFile) } : u))
      }
      const res = await extract(registry, contractFile, task.signal)
      if (!task.isCurrent()) return
      // 이어 받은 계약서는 늘 실제 계약서다 (liveCarry). 예시 계약서는 여기까지 오지 않는다
      const contract = carry?.contract ?? res.contract
      if (!contract) {
        throw new ApiError(
          '계약서를 읽지 못했어요. 계약서 사진이나 PDF를 다시 올려 주세요.',
          'NOT_CONTRACT',
          null,
          'contract',
        )
      }
      setRecheckDraft({
        registry: res.registry,
        contract,
        baseline_viewed_at: carry?.baselineViewedAt ?? null,
        today: null,
        mode: 'live',
      })
      show({ name: 'recheck-confirm' })
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
      show({ name: 'progress', phase: 'recheck', startedAt, hasContract: true, source: req.mode })
    }, CHECK_PROGRESS_DELAY_MS)
    try {
      const result = await recheck(req, task.signal)
      if (!task.isCurrent()) return
      setRecheckReport(result)
      show({ name: 'recheck-report' })
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
      // 예시 계약서는 이어 받지 않는다 (다시 확인할 때는 내 서류를 올린다)
      setRecheckCarry(null)
      setRecheckDraft(req)
      setRecheckReport(result)
      show({ name: 'recheck-report' })
    } catch (err) {
      if (task.isCurrent()) showError('recheck-demo', task, err)
    } finally {
      task.finish()
      if (task.isCurrent()) setRecheckDemoLoading(false)
    }
  }

  /** S5 3절 → 수정된 계약서 올리기 */
  function openCompare() {
    stopRunning()
    setCompareContract(null)
    setCompareConsent(false)
    show({ name: 'compare-upload' })
  }

  /** 비교와 수정 후 검사를 함께 돌린다 (같은 입력이면 같은 결과, AI를 부르지 않는다) */
  async function compareAndCheck(req: CompareRequest, task: Task) {
    const [cmp, afterReport] = await Promise.all([compare(req, task.signal), check(req.after, task.signal)])
    if (!task.isCurrent()) return
    setCompareReport(cmp)
    setCompareAfter({ request: req.after, report: afterReport })
    show({ name: 'compare-report' })
  }

  /** 고친 계약서 읽기 → 비교 (수정 전 = 지금의 검사 입력, 수정 후 = 계약서만 바꾼 입력) */
  async function runCompareExtract() {
    const before = request
    const pick = compareContract
    if (!before || !pick || !compareConsent) return
    const task = beginTask()
    let stage: ErrorPhase = 'compare-extract'
    show({ name: 'progress', phase: 'compare-extract', startedAt: Date.now(), hasContract: true, source: 'live' })
    try {
      const file = (await contractFileToSend(pick)) ?? pick.file
      if (!task.isCurrent()) return
      setCompareContract((c) => (c === pick ? sentPick(pick, file) : c))
      const contract = await extractContract(file, task.signal)
      if (!task.isCurrent()) return
      const req: CompareRequest = {
        before,
        after: { ...before, contract },
        today: before.today,
        mode: before.mode,
      }
      setCompareDraft(req)
      stage = 'compare'
      // 수정된 계약서는 방금 실제로 읽었으므로 "완료"로 보인다 (수정 전이 예시여도)
      show({ name: 'progress', phase: 'compare', startedAt: Date.now(), hasContract: true, source: 'live' })
      await compareAndCheck(req, task)
    } catch (err) {
      if (task.isCurrent()) showError(stage, task, err)
    } finally {
      task.finish()
    }
  }

  /** 비교만 다시 시도 */
  async function runCompare(req: CompareRequest) {
    const task = beginTask()
    const source = compareContract ? 'live' : req.mode // 올린 계약서가 있으면 그 계약서를 읽은 비교다
    show({ name: 'progress', phase: 'compare', startedAt: Date.now(), hasContract: true, source })
    try {
      await compareAndCheck(req, task)
    } catch (err) {
      if (task.isCurrent()) showError('compare', task, err)
    } finally {
      task.finish()
    }
  }

  /** S1 예시 "C 집, 요청서대로 계약서를 고친 경우" → S8 */
  async function loadCompareDemo() {
    const task = beginTask()
    setCompareDemoLoading(true)
    setCompareContract(null)
    try {
      const req = await demoCompare(task.signal)
      if (!task.isCurrent()) return
      setCompareDraft(req)
      await compareAndCheck(req, task)
    } catch (err) {
      if (task.isCurrent()) showError('compare-demo', task, err)
    } finally {
      task.finish()
      if (task.isCurrent()) setCompareDemoLoading(false)
    }
  }

  /** S8 [수정된 계약서로 검토서 보기]: 수정 후 입력·결과가 지금의 검토서가 된다 */
  function openAfterReport() {
    if (!compareAfter) return
    stopRunning()
    setRequest(compareAfter.request)
    setReport(compareAfter.report)
    setReviewFocus(null)
    show({ name: 'report' })
  }

  /** 처음으로: 메모리의 서류·결과를 모두 버리고, 브라우저 기록도 첫 칸으로 돌린다 */
  function goHome() {
    stopRunning()
    setCompareContract(null)
    setCompareConsent(false)
    setCompareDraft(null)
    setCompareReport(null)
    setCompareAfter(null)
    setReviewFocus(null)
    setUpload(emptyUploadDraft())
    setRequest(null)
    setReport(null)
    setRecheckCarry(null)
    setRecheckUpload(emptyRecheckUpload())
    setRecheckDraft(null)
    setRecheckReport(null)
    const n = nav.current
    setView(START)
    if (n.idx > 0) {
      const steps = n.idx
      n.idx = 0
      window.history.go(-steps)
    }
  }

  /** 개인정보 처리 안내에서 [돌아가기] */
  function leavePrivacy() {
    const n = nav.current
    const prev = n.stack[n.idx - 1]
    if (prev) backTo(prev)
    else go(START)
  }

  const openPrivacy = () => go({ name: 'privacy' })
  const backToReport = report ? () => backTo({ name: 'report' }) : undefined

  const demoMarker =
    view.name === 'compare-report'
      ? compareReport?.mode === 'demo'
      : view.name === 'recheck-report'
      ? recheckReport?.mode === 'demo'
      : view.name === 'progress' && (view.phase === 'recheck' || view.phase === 'compare')
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
          onUpload={() => go({ name: 'upload' })}
          onDemo={loadDemo}
          demoLoading={demoLoading}
          onRecheck={() => openRecheck(null)}
          onRecheckDemo={loadRecheckDemo}
          recheckDemoLoading={recheckDemoLoading}
          onCompareDemo={loadCompareDemo}
          compareDemoLoading={compareDemoLoading}
          onPrivacy={openPrivacy}
        />
      )
      break
    case 'privacy':
      screen = <PrivacyScreen onBack={leavePrivacy} />
      break
    case 'upload':
      screen = (
        <UploadScreen
          draft={upload}
          setDraft={setUpload}
          onSubmit={runExtract}
          onHome={goHome}
          onPrivacy={openPrivacy}
        />
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
          onCancel={() => backTo(progressOrigin(view.phase))}
        />
      )
      break
    case 'error': {
      const { phase } = view
      screen = (
        <ErrorScreen
          key={`${phase}-${view.at}`}
          phase={phase}
          message={view.message}
          code={view.code}
          document={view.document}
          fileError={isFileError(view.code)}
          retrying={checking}
          onRetry={() => {
            if (phase === 'extract') void runExtract()
            else if (phase === 'check' && request) void runCheck(request)
            else if (phase === 'recheck-extract') void runRecheckExtract()
            else if (phase === 'recheck' && recheckDraft) void runRecheck(recheckDraft)
            else if (phase === 'recheck-demo') void loadRecheckDemo()
            else if (phase === 'compare-extract') void runCompareExtract()
            else if (phase === 'compare' && compareDraft) void runCompare(compareDraft)
            else if (phase === 'compare-demo') void loadCompareDemo()
            else void loadDemo(lastDemo)
          }}
          onBack={() => backTo(errorOrigin(phase))}
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
            backTo({ name: 'review' })
          }}
          onFillMissing={(unknownRuleIds) => {
            backTo({ name: 'review' })
            setReviewFocus(unknownRuleIds)
          }}
          onCompare={openCompare}
          onRecheck={() =>
            openRecheck(liveCarry(request?.contract, request?.registry.viewed_at, request?.mode))
          }
          onHome={goHome}
        />
      ) : null
      break
    case 'compare-upload':
      screen = (
        <CompareUploadScreen
          contract={compareContract}
          setContract={setCompareContract}
          consent={compareConsent}
          setConsent={setCompareConsent}
          onSubmit={runCompareExtract}
          onBack={() => backTo(report ? { name: 'report' } : START)}
          onPrivacy={openPrivacy}
          onHome={goHome}
        />
      )
      break
    case 'compare-report':
      screen = compareReport ? (
        <CompareReportScreen report={compareReport} onOpenAfter={openAfterReport} onHome={goHome} />
      ) : null
      break
    case 'recheck':
      screen = (
        <RecheckUploadScreen
          carry={recheckCarry}
          upload={recheckUpload}
          setUpload={setRecheckUpload}
          onSubmit={runRecheckExtract}
          onDropCarry={() => setRecheckCarry(null)}
          onBackToReport={backToReport}
          onPrivacy={openPrivacy}
          onHome={goHome}
        />
      )
      break
    case 'recheck-confirm':
      screen = recheckDraft ? (
        <RecheckConfirmScreen
          key={recheckDraft.registry.viewed_at ?? 'confirm'}
          draft={recheckDraft}
          checking={checking}
          onRecheck={runRecheck}
          onReselect={() => backTo({ name: 'recheck' })}
          onBackToReport={backToReport}
          onHome={goHome}
        />
      ) : null
      break
    case 'recheck-report':
      screen = recheckReport ? (
        <RecheckReportScreen
          report={recheckReport}
          onAgain={() =>
            openRecheck(
              recheckDraft
                ? liveCarry(recheckDraft.contract, recheckDraft.baseline_viewed_at, recheckDraft.mode)
                : recheckCarry,
            )
          }
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
