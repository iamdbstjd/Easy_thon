// 계약서 자동 가리기에 쓰는 파일을 node_modules에서 public/으로 복사한다.
// - public/ocr/: 사진 글자 읽기(OCR, src/lib/autoMask.ts)의 엔진·영어 모델
// - public/pdfjs/: PDF 쪽 그리기(src/lib/pdfPages.ts)의 pdf.js 일꾼·글꼴 지도(cmaps)·표준 글꼴·wasm·색 프로필
// 사진·PDF가 기기 밖으로 나가지 않도록 둘 다 브라우저 안에서 돌고, 파일도 CDN이 아니라 우리 주소에서 받는다.
// npm run dev·build 앞에서 자동으로 돈다. 두 폴더는 만들어지는 폴더라 저장소에 올리지 않는다.
import { copyFileSync, cpSync, mkdirSync, statSync } from 'node:fs'
import { createRequire } from 'node:module'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const require = createRequire(import.meta.url)
const tesseractDir = dirname(require.resolve('tesseract.js/package.json'))
// tesseract.js-core는 tesseract.js가 쓰는 판을 찾는다
const coreDir = dirname(createRequire(join(tesseractDir, 'package.json')).resolve('tesseract.js-core/package.json'))
const engDir = dirname(require.resolve('@tesseract.js-data/eng/package.json'))
const out = join(here, '..', 'public', 'ocr')

const files = [
  [join(tesseractDir, 'dist', 'worker.min.js'), 'worker.min.js'],
  // 글자 읽기 엔진: 기기가 되는 것(relaxed SIMD → SIMD → 기본)을 tesseract가 골라 하나만 받는다
  [join(coreDir, 'tesseract-core-relaxedsimd-lstm.wasm.js'), 'tesseract-core-relaxedsimd-lstm.wasm.js'],
  [join(coreDir, 'tesseract-core-simd-lstm.wasm.js'), 'tesseract-core-simd-lstm.wasm.js'],
  [join(coreDir, 'tesseract-core-lstm.wasm.js'), 'tesseract-core-lstm.wasm.js'],
  // 영어·숫자 모델(LSTM best_int). 주민등록번호·전화번호·계좌번호는 숫자와 하이픈이라 영어 모델로 읽는다
  [join(engDir, '4.0.0_best_int', 'eng.traineddata.gz'), 'eng.traineddata.gz'],
]

mkdirSync(out, { recursive: true })
let copied = 0
for (const [from, name] of files) {
  const to = join(out, name)
  const src = statSync(from)
  let same = false
  try {
    const dst = statSync(to)
    same = dst.size === src.size && dst.mtimeMs >= src.mtimeMs
  } catch {
    // 아직 없다
  }
  if (!same) {
    copyFileSync(from, to)
    copied += 1
  }
}
console.log(`copy-ocr: public/ocr ${copied ? `${copied}개 복사` : '그대로'}`)

// pdf.js: 옛 브라우저용(legacy) 일꾼과, 한글 PDF를 그리는 데 필요한 글꼴 지도·표준 글꼴, JPX·JBIG2 그림과 색 프로필을 푸는 wasm
const pdfjsDir = dirname(require.resolve('pdfjs-dist/package.json'))
const pdfOut = join(here, '..', 'public', 'pdfjs')
mkdirSync(join(pdfOut, 'wasm'), { recursive: true })
copyFileSync(join(pdfjsDir, 'legacy', 'build', 'pdf.worker.min.mjs'), join(pdfOut, 'pdf.worker.min.mjs'))
for (const dir of ['cmaps', 'standard_fonts', 'iccs']) {
  cpSync(join(pdfjsDir, dir), join(pdfOut, dir), { recursive: true })
}
// 스크립트 실행(quickjs)은 쓰지 않으므로 그림·색에 쓰는 것만
for (const name of [
  'openjpeg.wasm',
  'openjpeg_nowasm_fallback.js',
  'jbig2.wasm',
  'jbig2_nowasm_fallback.js',
  'qcms_bg.wasm',
  'LICENSE_OPENJPEG',
  'LICENSE_PDFJS_OPENJPEG',
  'LICENSE_JBIG2',
  'LICENSE_PDFJS_JBIG2',
  'LICENSE_QCMS',
  'LICENSE_PDFJS_QCMS',
]) {
  copyFileSync(join(pdfjsDir, 'wasm', name), join(pdfOut, 'wasm', name))
}
console.log('copy-ocr: public/pdfjs 복사')
