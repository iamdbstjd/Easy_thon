/**
 * 글자를 클립보드에 복사한다. 성공하면 true.
 * 노트북 IP로 접속한 휴대폰처럼 보안 컨텍스트가 아니면 navigator.clipboard가 없어서 예전 방식으로 복사한다.
 */
export async function copyText(text: string): Promise<boolean> {
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // 아래 방식으로 다시 시도한다
    }
  }
  const active = document.activeElement instanceof HTMLElement ? document.activeElement : null
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.top = '0'
  area.style.left = '0'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  }
  area.remove()
  active?.focus()
  return ok
}
