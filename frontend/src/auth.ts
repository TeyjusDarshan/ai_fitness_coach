import {
  startAuthentication,
  startRegistration,
  WebAuthnError,
  type PublicKeyCredentialCreationOptionsJSON,
  type PublicKeyCredentialRequestOptionsJSON,
} from '@simplewebauthn/browser'
import { request } from './api'

export interface Me {
  user_id: string
}

export type RegistrationOptions = PublicKeyCredentialCreationOptionsJSON
export type LoginOptions = PublicKeyCredentialRequestOptionsJSON

export function fetchMe(): Promise<Me> {
  return request<Me>('/auth/me')
}

export function logoutRequest(): Promise<void> {
  return request<void>('/auth/logout', { method: 'POST' })
}

// Options are fetched ahead of the tap that uses them: iOS Safari only lets
// navigator.credentials.* run straight from a user gesture, so the button
// handler must call startRegistration/startAuthentication without first
// awaiting a network round trip.
export function fetchRegistrationOptions(enrollmentToken: string): Promise<RegistrationOptions> {
  return request<RegistrationOptions>('/auth/register/options', {
    method: 'POST',
    body: JSON.stringify({ enrollment_token: enrollmentToken }),
  })
}

export async function enrollPasskey(enrollmentToken: string, optionsJSON: RegistrationOptions): Promise<Me> {
  const credential = await startRegistration({ optionsJSON })
  return request<Me>('/auth/register/verify', {
    method: 'POST',
    body: JSON.stringify({ enrollment_token: enrollmentToken, credential }),
  })
}

export function fetchLoginOptions(): Promise<LoginOptions> {
  return request<LoginOptions>('/auth/login/options', { method: 'POST' })
}

export async function signInWithPasskey(optionsJSON: LoginOptions, useBrowserAutofill = false): Promise<Me> {
  const credential = await startAuthentication({ optionsJSON, useBrowserAutofill })
  return request<Me>('/auth/login/verify', { method: 'POST', body: JSON.stringify({ credential }) })
}

// null means "the user backed out" (dismissed the passkey sheet, or a newer
// passkey prompt replaced this one) — nothing to show as an error.
export function passkeyErrorMessage(error: unknown): string | null {
  if (error instanceof WebAuthnError) {
    if (error.code === 'ERROR_CEREMONY_ABORTED') return null
    if (error.code === 'ERROR_AUTHENTICATOR_PREVIOUSLY_REGISTERED') {
      return 'This device already has a passkey for your account — sign in instead.'
    }
  }
  if (error instanceof Error && (error.name === 'NotAllowedError' || error.name === 'AbortError')) return null
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}
