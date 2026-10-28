import { Icon, type IconName } from './Icon'
import { Laurel } from './Laurel'

export type SharePhase = 'uploading' | 'upload-failed' | 'opening' | 'done'

type RowState = 'done' | 'active' | 'pending' | 'failed'

// Full-screen progress while the workout and voice note go to the coach:
// the voice note uploads to storage, then WhatsApp opens with the summary.
// Stays up afterwards as the "sent" confirmation. See SummaryScreen.
export function ShareProgress({
  phase,
  hasVoice,
  onRetry,
  onSkipVoice,
  onBack,
}: {
  phase: SharePhase
  hasVoice: boolean
  onRetry: () => void
  onSkipVoice: () => void
  onBack: () => void
}) {
  const voice: RowState = phase === 'uploading' ? 'active' : phase === 'upload-failed' ? 'failed' : 'done'
  const whatsapp: RowState = phase === 'opening' ? 'active' : phase === 'done' ? 'done' : 'pending'
  const busy = phase === 'uploading' || phase === 'opening'

  return (
    <div className="share-progress" role="status" aria-live="polite">
      <div className="share-progress__inner">
        <div className="share-progress__art" aria-hidden>
          <Laurel side="left" />
          <svg viewBox="0 0 140 110" className="share-progress__cloud">
            <ellipse cx="70" cy="100" rx="42" ry="4" fill="#cfdccf" opacity=".6" />
            <circle cx="52" cy="62" r="24" fill="#cfe5d6" />
            <circle cx="84" cy="56" r="30" fill="#bfdcc9" />
            <rect x="34" y="62" width="76" height="26" rx="13" fill="#d8ebde" />
            <path d="M70 80V46M56 59l14-15 14 15" stroke="#1f5c45" strokeWidth="9" strokeLinecap="round" strokeLinejoin="round" fill="none" />
          </svg>
          <Laurel side="right" />
          <span className="share-progress__dot share-progress__dot--a" />
          <span className="share-progress__dot share-progress__dot--b" />
          <span className="share-progress__dot share-progress__dot--c" />
        </div>

        <h1 className="share-progress__title">
          {hasVoice ? 'Uploading Your Workout & Voice Note' : 'Uploading Your Workout'}
        </h1>
        <p className="share-progress__text">Just a moment, we&apos;re sending everything to your coach.</p>

        <ul className="share-progress__steps">
          <Step icon="file" title="Uploading workout summary" detail="Sets, exercises, duration" state="done" />
          {hasVoice && (
            <Step
              icon="mic"
              title={voice === 'failed' ? "Couldn't upload voice note" : 'Uploading voice note'}
              detail={voice === 'failed' ? 'Check your connection and try again' : 'Your feedback for your coach'}
              state={voice}
            >
              {voice === 'failed' && (
                <div className="share-progress__actions">
                  <button className="btn-link" onClick={onRetry}>
                    Try again
                  </button>
                  <button className="btn-link" onClick={onSkipVoice}>
                    Share without voice note
                  </button>
                </div>
              )}
            </Step>
          )}
          <Step
            icon="whatsapp"
            title="Preparing to open WhatsApp"
            detail="You'll be redirected automatically"
            state={whatsapp}
          />
        </ul>

        <div className="share-progress__thanks">
          <div className="share-progress__divider" aria-hidden>
            <span />
            <svg viewBox="0 0 24 24" width="26" height="26">
              <path
                fill="none"
                stroke="currentColor"
                strokeWidth="1.8"
                strokeLinejoin="round"
                d="M12 20.5s-7.5-4.5-9.3-9.3C1.5 8 3.6 5 6.6 5c2 0 3.5 1.1 5.4 3.1C13.9 6.1 15.4 5 17.4 5c3 0 5.1 3 3.9 6.2-1.8 4.8-9.3 9.3-9.3 9.3Z"
              />
            </svg>
            <span />
          </div>
          <p className="share-progress__thanks-title">Thanks for sharing your progress with your coach!</p>
          <p className="share-progress__thanks-text">Your feedback helps them support you better.</p>
        </div>

        <button className="btn-secondary share-progress__back" disabled={busy} onClick={onBack}>
          <Icon name="arrowLeft" size={20} />
          Back to Dashboard
        </button>
      </div>
    </div>
  )
}

function Step({
  icon,
  title,
  detail,
  state,
  children,
}: {
  icon: IconName
  title: string
  detail: string
  state: RowState
  children?: React.ReactNode
}) {
  return (
    <li className="share-step">
      <span className="share-step__icon">
        <Icon name={icon} size={24} />
      </span>
      <div className="share-step__body">
        <div className="share-step__title">{title}</div>
        <div className="share-step__detail">{detail}</div>
        {children}
      </div>
      <span className={`share-step__state share-step__state--${state}`} aria-hidden>
        {state === 'done' && <Icon name="check" size={18} />}
        {state === 'failed' && '!'}
      </span>
    </li>
  )
}
