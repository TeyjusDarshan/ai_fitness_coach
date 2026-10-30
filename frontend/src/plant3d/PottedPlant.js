import * as THREE from 'three';
import { Butterfly } from './Butterfly.js';
import { Flower } from './Flower.js';
import { Tube, UP, clamp01, createLeafGeometry, easeOutBack, perpendicular, smoothstep } from './geometry.js';

export const CAPTIONS = [
  'An empty pot, ready for a seed',
  'A seedling appears',
  'Its first leaf unfurls',
  'Three new leaves grow',
  'Three more leaves grow',
  'A small bud forms',
  'The first flower blooms',
  'Two new buds rise',
  'Two more flowers bloom',
  'It grows into a flowering bush',
  'A butterfly arrives',
  'A second butterfly joins',
];
export const LAST_STEP = CAPTIONS.length - 1;

// The step each stage happens on (steps 1–4 are the seedling and its leaves, below).
const STEP = { BUD: 5, BLOOM: 6, SIDE_BUDS: 7, SIDE_BLOOMS: 8, BUSH: 9, BUTTERFLY_1: 10, BUTTERFLY_2: 11 };

// Angles are measured around the stem, from the camera (+Z) towards +X.
const RIGHT = Math.PI / 2;
const LEFT = -Math.PI / 2;

const STEM_POINTS = [
  [0, 0, 0],
  [0.03, 0.45, 0.02],
  [-0.03, 0.95, 0],
  [0.02, 1.45, -0.01],
  [0, 1.95, 0.02],
];
// Main stem height at each step.
const STEM_HEIGHT = [0, 0.32, 0.55, 0.85, 1.15, 1.5, 1.65, 1.75, 1.82, 1.9, 1.9, 1.9];

const LEAVES = [
  // Seed leaves.
  { step: 1, u: 0.13, angle: RIGHT - 0.2, size: 0.26, wide: true },
  { step: 1, u: 0.13, angle: LEFT + 0.2, size: 0.26, wide: true },
  { step: 2, u: 0.25, angle: RIGHT - 0.4, size: 0.5 },
  { step: 3, u: 0.3, angle: LEFT + 0.3, size: 0.52, delay: 0 },
  { step: 3, u: 0.36, angle: RIGHT + 0.6, size: 0.5, delay: 0.15 },
  { step: 3, u: 0.42, angle: LEFT - 0.5, size: 0.48, delay: 0.3 },
  { step: 4, u: 0.48, angle: RIGHT - 0.7, size: 0.46, delay: 0 },
  { step: 4, u: 0.53, angle: LEFT + 0.7, size: 0.44, delay: 0.15 },
  { step: 4, u: 0.58, angle: RIGHT + 0.9, size: 0.42, delay: 0.3 },
];

// Flower stems branching off the main stem: [step, u, angle, length, rise, colour, size, delay].
const SIDE_FLOWERS = [
  { step: STEP.SIDE_BUDS, u: 0.62, angle: RIGHT - 0.5, length: 0.55, rise: 0.55, color: '#ff8cc6', size: 0.36 },
  { step: STEP.SIDE_BUDS, u: 0.7, angle: LEFT + 0.5, length: 0.55, rise: 0.5, color: '#c77dff', size: 0.36, delay: 0.15 },
  { step: STEP.BUSH, u: 0.42, angle: RIGHT - 0.3, length: 0.4, rise: 0.25, color: '#ffb3d9', size: 0.3 },
  { step: STEP.BUSH, u: 0.5, angle: LEFT + 0.3, length: 0.42, rise: 0.25, color: '#ff6f91', size: 0.3, delay: 0.08 },
  { step: STEP.BUSH, u: 0.57, angle: 0.2, length: 0.32, rise: 0.15, color: '#ffd166', size: 0.28, delay: 0.16 },
  { step: STEP.BUSH, u: 0.78, angle: RIGHT - 0.2, length: 0.34, rise: 0.25, color: '#c77dff', size: 0.28, delay: 0.24 },
  { step: STEP.BUSH, u: 0.84, angle: LEFT + 0.2, length: 0.32, rise: 0.25, color: '#ff8fab', size: 0.28, delay: 0.32 },
  { step: STEP.BUSH, u: 0.66, angle: -0.3, length: 0.3, rise: 0.2, color: '#ff5fa2', size: 0.27, delay: 0.4 },
];

// Stems that spring up from the soil when the plant turns into a bush,
// fanned all the way round so the bush is full from every side.
const BUSH_COLORS = ['#ff5fa2', '#ffb3d9', '#c77dff', '#ff8fab', '#ffd166', '#ff6f91', '#e85dff'];
const BUSH_STEMS = [-2.5, -1.7, -0.9, -0.15, 0.6, 1.4, 2.3].map((angle, i) => ({
  angle,
  lean: 0.6 + 0.12 * Math.cos(i * 2.1),
  height: 1.3 + 0.2 * Math.sin(i * 1.7),
  delay: [0.18, 0.06, 0, 0.12, 0.03, 0.09, 0.21][i], // stagger the order they shoot up
  color: BUSH_COLORS[i],
  sideColor: BUSH_COLORS[(i + 3) % BUSH_COLORS.length],
}));

const BUTTERFLIES = [
  { step: STEP.BUTTERFLY_1, color: '#ff9f1c', phase: 0, home: new THREE.Vector3(1.2, 2.0, 1.2) },
  { step: STEP.BUTTERFLY_2, color: '#4cc9f0', phase: 1.7, home: new THREE.Vector3(-1.2, 1.8, 1.2) },
];

const LEAF_GREEN = new THREE.Color('#4f9a34');
const GLOW = new THREE.Color('#ffd27a');
const leafGeometry = createLeafGeometry();

/** Value of a per-step table at fractional step s, eased between steps. */
function keyed(table, s) {
  const i = Math.floor(s);
  if (i < 0) return table[0];
  if (i >= table.length - 1) return table[table.length - 1];
  return table[i] + (table[i + 1] - table[i]) * smoothstep(0, 1, s - i);
}

/** Progress 0..1 of something that appears during `step`, optionally starting a little later. */
const appear = (s, step, delay = 0) => clamp01((s - (step - 1) - delay) / (1 - delay));

/** Magic glow for a change in progress: zero at both ends, brightest midway. */
const glowOf = (p) => Math.sin(Math.PI * p) * 0.9;

export class PottedPlant extends THREE.Group {
  constructor() {
    super();
    this.s = -1;
    this.add(createPot());

    this.plant = new THREE.Group(); // everything that sways
    this.add(this.plant);

    // Main stem.
    this.curve = new THREE.CatmullRomCurve3(STEM_POINTS.map((p) => new THREE.Vector3(...p)));
    this.stemLength = this.curve.getLength();
    this.stemMaterial = new THREE.MeshStandardMaterial({ color: '#5f9a3a', roughness: 0.7 });
    this.stemTube = new Tube(40, 10);
    this.stem = new THREE.Mesh(this.stemTube.geometry, this.stemMaterial);
    this.stem.castShadow = true;
    this.plant.add(this.stem);

    this.leaves = LEAVES.map((spec) => this.createLeaf(spec));
    this.mainFlower = new Flower({ color: '#ff5fa2', size: 0.42 });
    this.plant.add(this.mainFlower);
    this.sideFlowers = SIDE_FLOWERS.map((spec) => this.createSideFlower(spec));
    for (const spec of BUSH_STEMS) this.createBushStem(spec);

    this.butterflies = BUTTERFLIES.map((spec) => {
      const b = new Butterfly(spec);
      this.add(b);
      return { ...spec, butterfly: b };
    });
  }

  /** Main stem tip at fractional step s. */
  stemTip(s, out = new THREE.Vector3()) {
    return this.curve.getPointAt(Math.max(0.001, keyed(STEM_HEIGHT, s) / this.stemLength), out);
  }

  createLeaf(spec, curve = this.curve) {
    const point = curve.getPointAt(spec.u);
    const tangent = curve.getTangentAt(spec.u);
    const forward = perpendicular(tangent, spec.angle, new THREE.Vector3()).addScaledVector(UP, 0.35).normalize();
    const up = UP.clone().addScaledVector(forward, -UP.dot(forward)).normalize();
    const side = new THREE.Vector3().crossVectors(up, forward);

    const holder = new THREE.Group();
    holder.position.copy(point);
    holder.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(side, up, forward));
    const material = new THREE.MeshStandardMaterial({ color: LEAF_GREEN, vertexColors: true, side: THREE.DoubleSide, roughness: 0.6 });
    const mesh = new THREE.Mesh(leafGeometry, material);
    mesh.castShadow = true;
    holder.add(mesh);
    holder.visible = false;
    this.plant.add(holder);

    const tip = point.clone().addScaledVector(forward, spec.size * 0.6);
    return { ...spec, delay: spec.delay ?? 0, holder, mesh, material, tip };
  }

  /** A short flowering stem branching off `parent` (the main stem by default). */
  createSideFlower(spec, parent = this.curve) {
    const start = parent.getPointAt(spec.u);
    const out = perpendicular(parent.getTangentAt(spec.u), spec.angle, new THREE.Vector3());
    const curve = new THREE.CatmullRomCurve3([
      start,
      start.clone().addScaledVector(out, spec.length * 0.45).add(new THREE.Vector3(0, spec.rise * 0.2, 0)),
      start.clone().addScaledVector(out, spec.length * 0.85).add(new THREE.Vector3(0, spec.rise * 0.6, 0)),
      start.clone().addScaledVector(out, spec.length).add(new THREE.Vector3(0, spec.rise, 0)),
    ]);
    return this.createFlowerStem(spec, curve, out);
  }

  /** A stem along `curve` with a flower at its tip, facing outwards (`out`) and towards the camera. */
  createFlowerStem(spec, curve, out) {
    const tube = new Tube(spec.segments ?? 14, 6);
    const stem = new THREE.Mesh(tube.geometry, this.stemMaterial);
    stem.castShadow = true;
    stem.visible = false;
    const flower = new Flower({ color: spec.color, size: spec.size });
    const axis = new THREE.Vector3(out.x * 0.6, 0.6, 0.8 + Math.max(0, out.z) * 0.3).normalize();
    this.plant.add(stem, flower);
    return { ...spec, delay: spec.delay ?? 0, radius: spec.radius ?? 0.016, curve, tube, stem, flower, axis, tip: curve.getPointAt(1) };
  }

  /** One of the stems that rise from the soil to turn the plant into a bush. */
  createBushStem({ angle, lean, height, delay, color, sideColor }) {
    const out = new THREE.Vector3(Math.sin(angle), 0, Math.cos(angle));
    const base = out.clone().multiplyScalar(0.16);
    const at = (reach, rise) => base.clone().addScaledVector(out, lean * reach).add(new THREE.Vector3(0, height * rise, 0));
    const curve = new THREE.CatmullRomCurve3([base, at(0.12, 0.35), at(0.5, 0.72), at(1, 1)]);

    const stem = this.createFlowerStem({ step: STEP.BUSH, delay, color, size: 0.32, radius: 0.022, segments: 18 }, curve, out);
    this.sideFlowers.push(stem);

    // Leaves along it, unfurling as the stem passes them.
    [0.32, 0.47, 0.62, 0.77].forEach((u, k) => {
      const side = (k % 2 ? 1 : -1) * (Math.PI / 2 + 0.3);
      const leaf = this.createLeaf({ step: STEP.BUSH, u, angle: side, size: 0.42 - u * 0.12, delay: Math.min(0.85, delay + 0.1 + u * 0.3) }, curve);
      this.leaves.push(leaf);
    });

    // And a second flower partway up.
    this.sideFlowers.push(
      this.createSideFlower(
        { step: STEP.BUSH, u: 0.62, angle: angle > 0 ? -1.2 : 1.2, length: 0.3, rise: 0.2, color: sideColor, size: 0.26, delay: Math.min(0.85, delay + 0.25) },
        curve,
      ),
    );
  }

  /** Points where the magic sparkles when step `k` happens. */
  eventPoints(k) {
    const pts = [];
    if (k === 1) pts.push(new THREE.Vector3(0, 0.05, 0), this.stemTip(1));
    for (const leaf of this.leaves) if (leaf.step === k) pts.push(leaf.tip);
    if (k === STEP.BUD || k === STEP.BLOOM) pts.push(this.stemTip(k));
    for (const f of this.sideFlowers) if (f.step === k || (f.step === STEP.SIDE_BUDS && k === STEP.SIDE_BLOOMS)) pts.push(f.tip);
    for (const b of this.butterflies) if (b.step === k) pts.push(b.butterfly.pos.clone());
    if (pts.length === 0) pts.push(this.stemTip(k));
    return pts;
  }

  /** Show the plant at fractional step s. */
  setStep(s) {
    if (s === this.s) return;
    this.s = s;

    // Main stem: grows taller and a little thicker.
    const height = keyed(STEM_HEIGHT, s);
    this.stem.visible = height > 0.001;
    if (this.stem.visible) {
      const r0 = 0.022 + 0.02 * (height / 1.9);
      this.stemTube.update(this.curve, height / this.stemLength, (t) => (t >= 1 ? 0.004 : r0 * (1 - 0.6 * t)));
    }
    const stemChange = s - Math.floor(s);
    this.stemMaterial.emissive.copy(GLOW).multiplyScalar(glowOf(stemChange) * 0.4 * (s < STEP.BUSH ? 1 : 0));

    // Leaves twirl open from nothing.
    for (const leaf of this.leaves) {
      const p = appear(s, leaf.step, leaf.delay);
      leaf.holder.visible = p > 0;
      if (!leaf.holder.visible) continue;
      const k = leaf.size * easeOutBack(p);
      leaf.mesh.scale.set(leaf.wide ? k * 1.5 : k, k, k);
      leaf.mesh.rotation.z = (1 - p) * 2.5;
      leaf.material.emissive.copy(GLOW).multiplyScalar(glowOf(p));
    }

    // Main flower: a small bud forms, then it grows and opens into a bloom.
    const budP = 0.55 * appear(s, STEP.BUD) + 0.45 * appear(s, STEP.BLOOM);
    const bloomP = appear(s, STEP.BLOOM);
    this.mainFlower.place(this.stemTip(s), new THREE.Vector3(0, 0.75, 0.66).normalize());
    this.mainFlower.set(budP, bloomP, Math.max(glowOf(appear(s, STEP.BUD)), glowOf(bloomP)));

    // Side flowers: the stem grows and a bud appears in their step, then they bloom
    // in the next step — except the bush, which grows and blooms all at once.
    for (const f of this.sideFlowers) {
      const grow = appear(s, f.step, f.delay);
      const blooming = f.step === STEP.SIDE_BUDS ? appear(s, STEP.SIDE_BLOOMS, f.delay) : smoothstep(0.45, 1, grow);
      f.stem.visible = grow > 0;
      f.flower.visible = grow > 0;
      if (!f.stem.visible) continue;
      const len = smoothstep(0, 0.7, grow);
      f.tube.update(f.curve, Math.max(0.01, len), (t) => (t >= 1 ? 0.003 : f.radius * (1 - 0.5 * t)));
      f.flower.place(f.curve.getPointAt(Math.max(0.01, len)), f.axis);
      f.flower.set(smoothstep(0.3, 1, grow), blooming, Math.max(glowOf(grow), glowOf(blooming)));
    }

    this.butterflyPresence = this.butterflies.map((b) => appear(s, b.step));
  }

  update(dt, time) {
    // A gentle sway, as if in a breeze.
    this.plant.rotation.z = Math.sin(time * 0.8) * 0.015;
    this.plant.rotation.x = Math.sin(time * 0.6 + 1) * 0.01;

    this.butterflies.forEach((b, i) => b.butterfly.update(dt, time, this.butterflyPresence[i]));
  }
}

function createPot() {
  const pot = new THREE.Group();
  const profile = [
    [0, -1.0],
    [0.5, -1.0],
    [0.68, -0.05],
    [0.78, -0.05],
    [0.78, 0.1],
    [0.7, 0.1],
    [0.66, -0.02],
  ].map(([x, y]) => new THREE.Vector2(x, y));
  const body = new THREE.Mesh(
    new THREE.LatheGeometry(profile, 48),
    new THREE.MeshStandardMaterial({ color: '#c96f45', roughness: 0.85, side: THREE.DoubleSide }),
  );
  body.castShadow = true;
  body.receiveShadow = true;

  const soil = new THREE.Mesh(new THREE.CircleGeometry(0.67, 40), new THREE.MeshStandardMaterial({ color: '#4a3226', roughness: 1 }));
  soil.rotation.x = -Math.PI / 2;
  soil.position.y = 0.0;
  soil.receiveShadow = true;

  pot.add(body, soil);
  return pot;
}
