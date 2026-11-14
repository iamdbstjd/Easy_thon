// 계약서 사진 자동 가리기(src/lib/autoMask.ts)에 쓰는 글자 읽기(OCR) 파일을 public/ocr/로 복사한다.
// 사진이 휴대폰 밖으로 나가지 않도록 OCR은 브라우저 안에서 돌고, 파일도 CDN이 아니라 우리 주소(/ocr/)에서 받는다.
// npm run dev·build 앞에서 자동으로 돈다. public/ocr/는 만들어지는 폴더라 저장소에 올리지 않는다.
import { copyFileSync, mkdirSync, statSync } from 'node:fs'
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
