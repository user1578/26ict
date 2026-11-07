import type { Validation } from '../types.ts'

export interface ValidationIssue {
  path: string
  message: string
}

/** 统一错误类型：真实后端与本地 mock 共用，App 只认 code / validation / issues。 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly validation?: Validation
  readonly issues?: ValidationIssue[]

  constructor(
    status: number,
    code: string,
    message: string,
    options: { validation?: Validation; issues?: ValidationIssue[] } = {},
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.validation = options.validation
    this.issues = options.issues
  }
}

export function describeApiError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.issues && error.issues.length > 0) {
      const preview = error.issues
        .slice(0, 3)
        .map((issue) => `${issue.path || '请求'}: ${issue.message}`)
        .join('；')
      return `请求校验失败（${error.status}）：${preview}`
    }
    if (error.code === 'revision_conflict') {
      return '服务端状态已变化，已刷新最新版本，请重新操作。'
    }
    if (error.code === 'verification_blocked') {
      return '未通过 B 端核验，不能建立正式版本。'
    }
    return `${error.code}：${error.message}`
  }
  if (error instanceof Error) {
    return error.message
  }
  return String(error)
}
