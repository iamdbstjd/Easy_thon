import { useEffect, useRef } from 'react'

/**
 * 화면이 바뀌면 맨 위로 올리고 제목(h1)에 초점을 옮긴다.
 * 화면 낭독기 사용자가 새 화면이 열렸다는 것을 알 수 있게 한다. 제목에는 tabIndex={-1}을 단다.
 */
export function useScreenFocus<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  useEffect(() => {
    window.scrollTo(0, 0)
    ref.current?.focus({ preventScroll: true })
  }, [])
  return ref
}
