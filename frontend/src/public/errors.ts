export type PublicTripFailureReason =
  | 'invalid_token'
  | 'expired'
  | 'revoked'
  | 'trip_finished'

export class PublicTripApiError extends Error {
  readonly status: number
  readonly reason?: PublicTripFailureReason

  constructor(status: number, message: string, reason?: PublicTripFailureReason) {
    super(message)
    this.name = 'PublicTripApiError'
    this.status = status
    this.reason = reason
  }
}
