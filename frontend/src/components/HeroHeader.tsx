import { Illustration } from './Illustration'

export function HeroHeader() {
  return (
    <div className="hero-header">
      <div className="hero-header__text">
        <div className="hero-header__title">
          Healthy Today
          <br />
          Stronger Tomorrow
        </div>
        <div className="hero-header__tagline">Stay active. Stay independent.</div>
        <span className="hero-header__underline" aria-hidden />
      </div>
      <Illustration className="hero-header__art" />
    </div>
  )
}
