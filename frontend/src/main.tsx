import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// 글꼴은 파일로 포함해서 인터넷이 없는 발표장에서도 같은 모양으로 보인다.
// 본문: Pretendard. 리포트 제목과 종합 판정: Noto Serif KR 700 (PRD 4.4). 필요한 글자 묶음만 내려받는다.
import 'pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css'
import '@fontsource/noto-serif-kr/700.css'
import './styles.css'
import App from './App.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
