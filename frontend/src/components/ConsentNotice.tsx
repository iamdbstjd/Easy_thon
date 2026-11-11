import { useId } from 'react'

/** 서류를 보내기 전 안내 문장. 개인정보 처리 안내 화면에도 같은 내용이 있다 */
export const CONSENT_TEXT =
  '올린 서류는 내용을 옮겨 적기 위해 OpenAI(미국)로 전송돼요. 우리 서버에는 저장하지 않고, OpenAI는 학습에 쓰지 않지만 남용 감시를 위해 최대 30일 보관할 수 있어요.'

/**
 * 서류를 AI로 보내기 전 확인 (S2·S6·수정된 계약서 올리기).
 * 확인하기 전에는 그 화면의 주 버튼을 누를 수 없다. 예시 보기에는 필요 없다.
 */
export function ConsentNotice({
  checked,
  onChange,
  onPrivacy,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  /** 개인정보 처리 안내 화면 열기 */
  onPrivacy: () => void
}) {
  const textId = useId()
  return (
    <div className="consent">
      <p id={textId}>{CONSENT_TEXT}</p>
      <p>
        <button type="button" className="link" onClick={onPrivacy}>
          개인정보 처리 안내
        </button>
      </p>
      <label className="check-row">
        <input
          type="checkbox"
          checked={checked}
          required
          aria-describedby={textId}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span>위 내용을 확인했어요</span>
      </label>
    </div>
  )
}
