export const ERROR_MESSAGES = {
  generic: '요청을 처리하지 못했어요. 잠시 후 다시 시도해 주세요.',
  network: '서버에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.',
  invalid: '입력한 값의 형식이 맞지 않아요. 날짜와 금액을 다시 확인해 주세요.',
  /** 503 BUSY: 서버가 문장을 보내지 않았을 때만 쓴다 (서버 문장과 같다) */
  busy: '지금 서류를 읽는 사람이 많아요. 잠시 후 다시 시도해 주세요.',
}

/** 파일·문서 오류가 어느 서류 때문인지 (서버가 알려 줄 때만) */
export type ErrorDocument = 'registry' | 'contract'

/** 사용자에게 보여줄 문장(message)과 오류 코드를 담는다. */
export class ApiError extends Error {
  readonly code: string | null
  readonly status: number | null
  readonly document: ErrorDocument | null

  constructor(
    message: string,
    code: string | null = null,
    status: number | null = null,
    document: ErrorDocument | null = null,
  ) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
    this.document = document
  }
}

/** 어떤 오류든 화면에 보여줄 한국어 문장으로 바꾼다. */
export function errorMessage(err: unknown): string {
  return err instanceof ApiError ? err.message : ERROR_MESSAGES.generic
}

/** 같은 파일로 다시 시도해도 소용없는 오류 (다른 파일을 골라야 한다) */
export function isFileError(code: string | null): boolean {
  return (
    code === 'UNSUPPORTED_FILE' ||
    code === 'NOT_REGISTRY' ||
    code === 'LAND_REGISTRY' ||
    code === 'NOT_CONTRACT' ||
    code === 'MASK_FAILED'
  )
}
