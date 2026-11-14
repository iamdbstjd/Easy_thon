import { Fragment, useId, useState } from 'react'
import { splitTerms } from '../content/glossary'
import type { GlossaryTerm } from '../content/glossary'

/**
 * 글 속의 어려운 말(content/glossary.ts)에 점선 밑줄을 친다. 누르면 그 글 끝에 쉬운 풀이가 나오고, 다시 누르면 닫힌다.
 * 글(text)은 가림(maskPersonal)을 마친 것을 넘긴다.
 */
export function Glossed({ text }: { text: string }) {
  const baseId = useId()
  const [open, setOpen] = useState<GlossaryTerm[]>([])
  const parts = splitTerms(text)
  if (parts.length === 1 && !parts[0].term) return <>{text}</>
  const noteId = (term: GlossaryTerm) => `${baseId}-${parts.findIndex((p) => p.term === term)}`
  const toggle = (term: GlossaryTerm) =>
    setOpen((current) => (current.includes(term) ? current.filter((t) => t !== term) : [...current, term]))
  return (
    <>
      {parts.map((part, i) =>
        part.term ? (
          <button
            key={i}
            type="button"
            className="term"
            aria-expanded={open.includes(part.term)}
            aria-controls={noteId(part.term)}
            title="누르면 쉬운 풀이가 나와요"
            onClick={() => toggle(part.term as GlossaryTerm)}
          >
            {part.text}
          </button>
        ) : (
          <Fragment key={i}>{part.text}</Fragment>
        ),
      )}
      {open.map((term) => (
        <span key={term.term} id={noteId(term)} className="term-note" role="note">
          <span className="term-note-word">{term.term}</span> {term.text}
        </span>
      ))}
    </>
  )
}
