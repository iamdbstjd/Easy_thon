import maskExample from '../assets/mask-example.webp'
import { useScreenFocus } from '../lib/useScreenFocus'

/** 개인정보 처리 안내 (서류 올리기 화면의 확인 문장과 처음 화면 아래에서 연다) */
export function PrivacyScreen({ onBack }: { onBack: () => void }) {
  const titleRef = useScreenFocus<HTMLHeadingElement>()

  return (
    <>
      <div className="doc-head">
        <h1 ref={titleRef} tabIndex={-1}>
          개인정보 처리 안내
        </h1>
        <p>서류를 올려 분석할 때 어떤 정보를 어디로 보내고 얼마나 두는지 알려 드려요.</p>
      </div>

      <section className="doc-section" aria-labelledby="privacy-what">
        <h2 id="privacy-what">받는 정보</h2>
        <ul className="dot-list">
          <li>등기부등본 PDF나 사진</li>
          <li>계약서 사진이나 PDF (올린 경우)</li>
          <li>직접 입력하거나 고친 값 (보증금, 월세, 계약 예정일, 임대인 이름, 선순위 보증금, 시세)</li>
        </ul>
      </section>

      <section className="doc-section" aria-labelledby="privacy-why">
        <h2 id="privacy-why">쓰는 목적</h2>
        <p>보증금을 잃을 수 있는 위험 신호를 확인하려고 서류 내용을 옮겨 적어요.</p>
      </section>

      <section className="doc-section" aria-labelledby="privacy-where">
        <h2 id="privacy-where">보내는 곳</h2>
        <dl className="rows">
          <div className="row">
            <dt>서류</dt>
            <dd>
              올린 서류 파일(등기부·계약서의 PDF나 사진)은 분석을 요청할 때만 OpenAI(미국)로 보내서 내용을 옮겨
              적어요.
            </dd>
          </div>
          <div className="row">
            <dt>시세·건축물대장</dt>
            <dd>
              등기부 주소 중 동 이름까지만(예: 경기도 용인시 수지구 죽전동) 행정안전부 주소 검색 서비스에 보내요.
              국토교통부 실거래가 공개 서비스에는 지역 번호와 연월만, 건축물대장 서비스에는 지역 번호와 번지만 보내요.
              이름과 동·호수는 보내지 않아요.
            </dd>
          </div>
          <div className="row">
            <dt>보내지 않음</dt>
            <dd>
              직접 입력한 값과 옮겨 적은 내용은 OpenAI로 보내지 않아요. 우리 서버에서만 위험 신호를 검사하고
              저장하지 않아요.
            </dd>
          </div>
        </dl>
      </section>

      <section className="doc-section" aria-labelledby="privacy-keep">
        <h2 id="privacy-keep">보관 기간</h2>
        <dl className="rows">
          <div className="row">
            <dt>우리 서버</dt>
            <dd>
              저장하지 않아요. 메모리에서 처리한 뒤 버려요. 로그에는 이름·주소·서류 원문을 남기지 않아요.
            </dd>
          </div>
          <div className="row">
            <dt>OpenAI</dt>
            <dd>
              학습에 쓰지 않고, 답도 저장하지 않게 해 두었어요. 다만 남용 감시를 위한 기록은 최대 30일 보관될 수
              있어요.
            </dd>
          </div>
        </dl>
      </section>

      <section className="doc-section" aria-labelledby="privacy-you">
        <h2 id="privacy-you">개인정보를 지키는 방법</h2>
        <ul className="dot-list">
          <li>
            계약서 사진은 보내기 전에 주민등록번호·전화번호·서명·계좌번호 같은 곳을 가릴 수 있어요. 흐리게 하는 게
            아니라 검게 칠해서, AI로 보내는 사진에서는 가린 곳이 완전히 지워져요.
          </li>
          <li>결과 화면에 나오는 주민등록번호와 전화번호는 저희가 자동으로 가려 드려요.</li>
          <li>
            계약서를 올리지 않고 보증금, 월세, 계약 예정일, 임대인 이름, 선순위 보증금을 직접 입력할 수 있어요.
            직접 입력한 값은 OpenAI로 보내지 않아요. 등기부등본은 꼭 올려야 해요.
          </li>
          <li>시세는 실거래로 찾아서 넣고, 틀리면 읽은 내용 확인 화면에서 고칠 수 있어요.</li>
        </ul>
        <figure className="privacy-figure">
          <img
            src={maskExample}
            width={390}
            height={520}
            alt="가상 계약서 사진의 임대인·임차인 칸에서 주민등록번호와 전화번호 줄, 서명 자리를 검은 네모 네 개로 가린 모습"
          />
          <figcaption>
            예시: 가상 계약서 사진에서 주민등록번호·전화번호 두 줄과 서명 두 곳을 가린 모습이에요. 네모로 가리거나
            손가락으로 칠해서 가릴 수 있어요.
          </figcaption>
        </figure>
      </section>

      <section className="doc-section" aria-labelledby="privacy-no">
        <h2 id="privacy-no">동의하지 않을 때</h2>
        <p>동의하지 않으면 서류 분석은 할 수 없지만, 예시 결과는 볼 수 있어요.</p>
      </section>

      <div className="actions">
        <button type="button" className="link" onClick={onBack}>
          돌아가기
        </button>
      </div>
    </>
  )
}
