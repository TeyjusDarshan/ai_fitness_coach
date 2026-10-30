import * as THREE from 'three'
import { Magic } from './Magic.js'
import { PottedPlant } from './PottedPlant.js'
import { smoothstep } from './geometry.js'

// Seconds each growth step takes.
const STEP_DURATION = 1.4
// The camera frames the plant from the pot's base to its top, which is
// roughly this high at each step (stem plus buds/flowers, bush at step 9).
// It grows unevenly — most of the height comes by the first bloom — so the
// framing follows it rather than the step number.
const PLANT_TOP = [0.1, 0.4, 0.65, 0.95, 1.25, 1.75, 2.0, 2.15, 2.25, 2.45, 2.45, 2.45]
const POT_BASE = -1.05
// Camera distance per unit of plant height framed, and the closest it comes
// (so the empty pot isn't oversized).
const DISTANCE_PER_HEIGHT = 1.95
const MIN_DISTANCE = 5.2
const MIN_LOOK_Y = -0.3

// Touching the plant sends a gust through it: a damped spring on its lean.
const GUST_STIFFNESS = 38 // springs back about once a second
const GUST_DAMPING = 2.2 // settles in ~2 s
const GUST_TAP = 0.9 // lean speed a tap gives
const GUST_SWIPE = 0.012 // lean speed per pixel swiped
const GUST_MAX_LEAN = 0.2 // radians

/** PLANT_TOP at fractional step s, eased between steps like the plant itself. */
function plantTop(s: number): number {
  const i = Math.max(0, Math.min(PLANT_TOP.length - 1, Math.floor(s)))
  if (i >= PLANT_TOP.length - 1) return PLANT_TOP[PLANT_TOP.length - 1]
  return PLANT_TOP[i] + (PLANT_TOP[i + 1] - PLANT_TOP[i]) * smoothstep(0, 1, s - i)
}

/**
 * The dashboard's 3D potted plant (from the plant/ prototype), drawn into a
 * transparent canvas filling `container`. `setStep` grows it to a step, with
 * sparkles for each new one; `dispose` must be called on unmount so the WebGL
 * context is released.
 */
export class PlantScene {
  private renderer: THREE.WebGLRenderer
  private scene = new THREE.Scene()
  private camera = new THREE.PerspectiveCamera(34, 1, 0.1, 50)
  private plant = new PottedPlant()
  private magic = new Magic()
  private clock = new THREE.Clock()
  private resizeObserver: ResizeObserver
  private distanceFactor = 1
  private lookAt = new THREE.Vector3()
  private step = 0 // where we're going
  private shown = 0 // fractional step currently on screen
  private container: HTMLElement
  private raycaster = new THREE.Raycaster()
  private pointer = new THREE.Vector2()
  private lean = 0 // extra sideways lean from gusts (radians, + = to the left)
  private leanSpeed = 0
  private dragX: number | null = null // last x of a drag that started on the plant

  constructor(container: HTMLElement) {
    this.container = container
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5))
    this.renderer.shadowMap.enabled = true
    this.renderer.shadowMap.type = THREE.PCFShadowMap
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping
    container.appendChild(this.renderer.domElement)

    this.scene.add(new THREE.HemisphereLight('#fff8ec', '#b9a27f', 1.5))
    const sun = new THREE.DirectionalLight('#fff1d6', 2.2)
    sun.position.set(2.5, 5, 3.5)
    sun.castShadow = true
    sun.shadow.mapSize.set(1024, 1024)
    Object.assign(sun.shadow.camera, { left: -2.5, right: 2.5, top: 3, bottom: -1.5, near: 1, far: 12 })
    sun.shadow.bias = -0.0005
    sun.shadow.normalBias = 0.02
    this.scene.add(sun)

    // A soft round shadow-catcher under the pot.
    const floor = new THREE.Mesh(new THREE.CircleGeometry(4, 48), new THREE.ShadowMaterial({ opacity: 0.18 }))
    floor.rotation.x = -Math.PI / 2
    floor.position.y = -1
    floor.receiveShadow = true
    this.scene.add(floor)

    this.scene.add(this.plant, this.magic)
    this.plant.setStep(0)

    this.resizeObserver = new ResizeObserver(() => this.fit())
    this.resizeObserver.observe(container)
    this.fit()

    const canvas = this.renderer.domElement
    canvas.addEventListener('pointerdown', this.onPointerDown)
    canvas.addEventListener('pointermove', this.onPointerMove)
    canvas.addEventListener('pointerup', this.onPointerUp)
    canvas.addEventListener('pointercancel', this.onPointerUp)

    this.renderer.setAnimationLoop(() => this.frame())
  }

  /** Grow (or shrink) to `step`; without `animate` it jumps straight there. */
  setStep(step: number, animate: boolean) {
    this.step = step
    if (!animate) {
      this.shown = step
      this.plant.setStep(step)
    }
  }

  dispose() {
    this.renderer.setAnimationLoop(null)
    const canvas = this.renderer.domElement
    canvas.removeEventListener('pointerdown', this.onPointerDown)
    canvas.removeEventListener('pointermove', this.onPointerMove)
    canvas.removeEventListener('pointerup', this.onPointerUp)
    canvas.removeEventListener('pointercancel', this.onPointerUp)
    this.resizeObserver.disconnect()
    this.scene.traverse((object) => {
      const mesh = object as THREE.Mesh
      mesh.geometry?.dispose()
      const materials = Array.isArray(mesh.material) ? mesh.material : mesh.material ? [mesh.material] : []
      for (const material of materials) material.dispose()
    })
    this.renderer.dispose()
    this.renderer.forceContextLoss()
    this.renderer.domElement.remove()
  }

  /** Whether the pointer event lands on the plant (or its pot). */
  private hitsPlant(event: PointerEvent): boolean {
    const rect = this.renderer.domElement.getBoundingClientRect()
    this.pointer.set(((event.clientX - rect.left) / rect.width) * 2 - 1, -((event.clientY - rect.top) / rect.height) * 2 + 1)
    this.raycaster.setFromCamera(this.pointer, this.camera)
    return this.raycaster.intersectObject(this.plant, true).length > 0
  }

  private onPointerDown = (event: PointerEvent) => {
    if (!this.hitsPlant(event)) return
    // Blow away from the finger: a touch on the right pushes it left.
    const rect = this.renderer.domElement.getBoundingClientRect()
    this.puff(event.clientX > rect.left + rect.width / 2 ? 1 : -1)
    this.dragX = event.clientX
    this.renderer.domElement.setPointerCapture(event.pointerId)
    navigator.vibrate?.(8)
  }

  /** A gust, as from a tap: `fromSide` 1 blows from the right (it leans left), -1 from the left. */
  puff(fromSide: 1 | -1 = 1) {
    this.leanSpeed += fromSide * GUST_TAP
  }

  // A swipe across the plant pushes it the way the finger moves.
  private onPointerMove = (event: PointerEvent) => {
    if (this.dragX === null) return
    this.leanSpeed -= (event.clientX - this.dragX) * GUST_SWIPE
    this.dragX = event.clientX
  }

  private onPointerUp = () => {
    this.dragX = null
  }

  /** Step the gust spring and apply it: the plant leans, and its leaves flutter while it moves. */
  private blow(dt: number, time: number) {
    this.leanSpeed += (-GUST_STIFFNESS * this.lean - GUST_DAMPING * this.leanSpeed) * dt
    this.lean = Math.max(-GUST_MAX_LEAN, Math.min(GUST_MAX_LEAN, this.lean + this.leanSpeed * dt))
    // PottedPlant.update has just set its gentle idle sway; add the gust on top.
    this.plant.plant.rotation.z += this.lean
    const flutter = Math.min(1, Math.abs(this.leanSpeed))
    this.plant.leaves.forEach((leaf, i) => {
      leaf.mesh.rotation.x = flutter * 0.35 * Math.sin(time * 18 + i * 1.7)
    })
  }

  private fit() {
    const { clientWidth: width, clientHeight: height } = this.container
    if (!width || !height) return
    const aspect = width / height
    this.camera.aspect = aspect
    this.camera.updateProjectionMatrix()
    this.renderer.setSize(width, height)
    // Back off on narrow boxes so the whole plant stays in view.
    this.distanceFactor = 1 / Math.min(1, aspect * 1.1)
  }

  /** Fire the magic for step k (forwards: it happens; backwards: it is undone). */
  private celebrate(k: number, forwards: boolean) {
    const points = this.plant.eventPoints(k)
    // Share ~400 sparks across the changes (fewer each when a whole bush appears at once).
    const perPoint = Math.min(90, Math.max(8, Math.round(400 / points.length)))
    for (const p of points) this.magic.burst(p, perPoint, !forwards)
    this.magic.pulse(points[0])
  }

  private frame() {
    const dt = Math.min(this.clock.getDelta(), 0.05)
    const time = this.clock.elapsedTime

    // Move towards the chosen step; hurry when several steps are owed.
    const before = this.shown
    const remaining = this.step - this.shown
    const speed = Math.max(1, Math.abs(remaining) * 0.8) / STEP_DURATION
    this.shown += Math.sign(remaining) * Math.min(Math.abs(remaining), speed * dt)

    // Step k starts when we pass k - 1 going forwards, and is undone when we pass k going back.
    if (this.shown > before) for (let m = Math.ceil(before); m < this.shown; m++) this.celebrate(m + 1, true)
    if (this.shown < before) for (let k = Math.floor(before); k > this.shown; k--) this.celebrate(k, false)

    this.plant.setStep(this.shown)
    this.plant.update(dt, time)
    this.blow(dt, time)
    this.magic.update(dt, time)

    // A slow drift instead of the prototype's pointer parallax (no hover on phones).
    const top = plantTop(this.shown)
    const lookY = Math.max(MIN_LOOK_Y, (POT_BASE + top) / 2)
    const distance = Math.max(MIN_DISTANCE, (top - POT_BASE) * DISTANCE_PER_HEIGHT) * this.distanceFactor
    this.lookAt.set(0, lookY, 0)
    this.camera.position.set(Math.sin(time * 0.25) * 0.35, lookY + 0.65 + Math.sin(time * 0.18) * 0.08, distance)
    this.camera.lookAt(this.lookAt)
    this.renderer.render(this.scene, this.camera)
  }
}
