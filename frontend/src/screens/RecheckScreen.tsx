import { useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import type { RecheckRequest } from '../api/types'
import { ConsentNotice } from '../components/ConsentNotice'
import { DocFilesField } from '../components/DocFilesField'
import { DateField, DateTimeField, ReadRow } from '../components/fields'
import { MAX_TOTAL_BYTES, totalBytes } from '../lib/files'
import { keepTogether } from '../lib/keepTogether'
import { maskPersonal } from '../lib/mask'
import { useScreenFocus } from '../lib/useScreenFocus'
import { recheckFormFrom, recheckRequestFrom } from '../state/recheck'
import type { RecheckCarry, RecheckForm, RecheckUpload } from '../state/recheck'

const INTRO = '잔금을 보내기 전과 입주 다음 날, 오늘 뗀 등기부를 계약서와 맞춰 봐요.'

/**
 * S6 계약 후 재확인: 오늘 뗀 등기부(필수)와 계약서(필수, 앞 화면에서 이어 왔으면 생략)를 올린다.
 * 아무것도 저장하지 않는다. 계약서는 같은 화면 흐름의 상태로만 이어 받는다.
 */
export function RecheckUploadScreen({
  carry,
  upload,
  setUpload,
  onSubmit,
  onDropCarry,
  onBackToReport,
  onPrivacy,
  onHome,
}: {
  carry: RecheckCarry | null
  upload: RecheckUpload
  setUpload: Dispatch<SetStateAction<RecheckUpload>>
  onSubmit: () => void
  /** [다른 계약서 올리기]: 이어 받은 계약서를 버리고 계약서를 새로 올린다 */
  onDropCarry: () => void
  /** 검토서가 있을 때만: [검토서로 돌아가기] */
  onBackToReport?: () => void
  onPrivacy: () => void
  onHome: () => void
}) {
  const titleRef = useScreenFocus<HTMLHeadingElement>()
  const [registryBusy, setRegistryBusy] = useState(false)
  const [contractBusy, setContractBusy] = useState(false)

  const contract = carry ? [] : upload.contract
  const tooBig = totalBytes([...upload.registry, ...contract].map((p) => p.file)) > MAX_TOTAL_BYTES
  const filesReady =
    upload.registry.length > 0 &&
    (carry !== null || upload.contract.length > 0) &&
    !registryBusy &&
    !contractBusy &&
    !tooBig
  const ready = filesReady && upload.consent

  return (
    <>
      <div className="doc-head">
        <h1 ref={titleRef} tabIndex={-1}>
          계약 후 재확인
        </h1>
        <p>{INTRO}</p>
      </div>

      <div className="rows mt-3">
        <DocFilesField
          label="오늘 뗀 등기부"
          doc="registry"
          required
          maskable={false}
          picks={upload.registry}
          describedBy="recheck-file-note"
          onChange={(update) => setUpload((u) => ({ ...u, registry: update(u.registry) }))}
          onBusyChange={setRegistryBusy}
        />
        {carry ? (
          <ReadRow label="계약서">
            <p>앞 화면의 계약서를 그대로 써요.</p>
            {carry.contract.address && (
              <p className="muted">{keepTogether(maskPersonal(carry.contract.address))}</p>
            )}
            <button type="button" className="link" onClick={onDropCarry}>
              다른 계약서 올리기
            </button>
          </ReadRow>
        ) : (
          <DocFilesField
            label="계약서"
            doc="contract"
            required
            maskable
            picks={upload.contract}
            describedBy="recheck-file-note"
            onChange={(update) => setUpload((u) => ({ ...u, contract: update(u.contract) }))}
            onBusyChange={setContractBusy}
          />
        )}
      </div>
      <p id="recheck-file-note" className="muted mt-1">
        PDF나 사진(JPG·PNG 등). 여러 장이면 한 번에 골라도 돼요. 파일 하나 10MB, 서류마다 30쪽까지
      </p>
      {tooBig && (
        <p className="form-error" role="alert">
          올린 파일이 모두 합쳐 20MB를 넘어요. 파일 수를 줄여 주세요.
        </p>
      )}

      <ConsentNotice
        checked={upload.consent}
        onChange={(consent) => setUpload((u) => ({ ...u, consent }))}
        onPrivacy={onPrivacy}
      />

      <div className="actions mt-2">
        <button
          type="button"
          className="btn-primary"
          disabled={!ready}
          aria-describedby={ready ? undefined : 'recheck-reason'}
          onClick={onSubmit}
        >
          서류 읽기
        </button>
        {onBackToReport && (
          <button type="button" className="link" onClick={onBackToReport}>
            검토서로 돌아가기
          </button>
        )}
        <button type="button" className="link" onClick={onHome}>
          처음으로
        </button>
      </div>
      {!ready && (
        <p id="recheck-reason" className="visually-hidden">
          {!filesReady
            ? tooBig
              ? '올린 파일이 모두 합쳐 20MB를 넘어요.'
              : carry
                ? '오늘 뗀 등기부를 고르면 읽을 수 있어요.'
                : '등기부와 계약서를 고르면 읽을 수 있어요.'
            : '위 내용을 확인하면 읽을 수 있어요.'}
        </p>
      )}
    </>
  )
}

/** S6 두 번째 단계: 읽은 날짜를 한 줄 표로 확인하고 고친다 (S4보다 짧게) */
export function RecheckConfirmScreen({
  draft,
  checking,
  onRecheck,
  onReselect,
  onBackToReport,
  onHome,
}: {
  draft: RecheckRequest
  checking: boolean
  onRecheck: (req: RecheckRequest) => void
  onReselect: () => void
  /** 검토서가 있을 때만: [검토서로 돌아가기] */
  onBackToReport?: () => void
  onHome: () => void
}) {
  const titleRef = useScreenFocus<HTMLHeadingElement>()
  const [initial] = useState(() => recheckFormFrom(draft))
  const [form, setForm] = useState<RecheckForm>(initial)

  function bind(key: keyof RecheckForm) {
    return { value: form[key], onChange: (value: string) => setForm((f) => ({ ...f, [key]: value })) }
  }

  return (
    <>
      <div className="doc-head">
        <h1 ref={titleRef} tabIndex={-1}>
          계약 후 재확인
        </h1>
        <p>읽은 날짜를 확인하세요. 틀린 곳이 있으면 고친 뒤 재확인하세요.</p>
      </div>

      <div className="rows mt-3">
        <DateField label="계약일" {...bind('contractDate')} />
        <DateField label="잔금일" {...bind('balanceDate')} />
        <DateField label="입주일" {...bind('moveInDate')} />
        <DateTimeField label="등기부 열람 일시" {...bind('viewedAt')} />
      </div>

      <div className="actions">
        <button
          type="button"
          className="btn-primary"
          disabled={checking}
          onClick={() => onRecheck(recheckRequestFrom(draft, form, initial))}
        >
          {checking ? '확인 중' : '재확인'}
        </button>
        <button type="button" className="link" disabled={checking} onClick={onReselect}>
          서류 다시 고르기
        </button>
        {onBackToReport && (
          <button type="button" className="link" disabled={checking} onClick={onBackToReport}>
            검토서로 돌아가기
          </button>
        )}
        <button type="button" className="link" disabled={checking} onClick={onHome}>
          처음으로
        </button>
      </div>
    </>
  )
}
