import { maskIds } from '../lib/mask'

/**
 * 문서에서 옮겨 온 부분: 1px 테두리 상자 + 출처 ("등기부 2쪽", "계약서", "시세" 등).
 * 원문에 주민등록번호 모양이 있으면 가려서 보여준다.
 */
export function Excerpt({ caption, text }: { caption: string; text: string }) {
  return (
    <figure className="excerpt">
      <figcaption className="excerpt-caption">{caption}</figcaption>
      <blockquote className="excerpt-text">{maskIds(text)}</blockquote>
    </figure>
  )
}
