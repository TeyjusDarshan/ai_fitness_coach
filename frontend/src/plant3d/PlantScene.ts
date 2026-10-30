import * as THREE from 'three'
import { Magic } from './Magic.js'
import { LAST_STEP, PottedPlant } from './PottedPlant.js'

// Seconds each growth step takes.
const STEP_DURATION = 1.4
// Camera framing for the empty pot and for the fully grown bush; it eases
// between them as the plant grows, so a small plant isn't lost in the box and
// a big one isn't cut off.
const FRAME_SMALL = { lookY: -0.25, distance: 4.6 }
const FRAME_FULL = { lookY: 0.8, distance: 6.3 }

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
    this.magic.update(dt, time)

    // A slow drift instead of the prototype's pointer parallax (no hover on phones).
    const grown = this.shown / LAST_STEP
    const lookY = FRAME_SMALL.lookY + (FRAME_FULL.lookY - FRAME_SMALL.lookY) * grown
    const distance = (FRAME_SMALL.distance + (FRAME_FULL.distance - FRAME_SMALL.distance) * grown) * this.distanceFactor
    this.lookAt.set(0, lookY, 0)
    this.camera.position.set(Math.sin(time * 0.25) * 0.35, lookY + 0.65 + Math.sin(time * 0.18) * 0.08, distance)
    this.camera.lookAt(this.lookAt)
    this.renderer.render(this.scene, this.camera)
  }
}
