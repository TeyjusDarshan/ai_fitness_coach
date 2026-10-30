import * as THREE from 'three';
import { Magic } from './effects/Magic.js';
import { CAPTIONS, LAST_STEP, PottedPlant } from './plant/PottedPlant.js';

// Seconds each transformation takes.
const STEP_DURATION = 1.4;

// ---------- scene ----------

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
document.getElementById('app').appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38, window.innerWidth / window.innerHeight, 0.1, 50);
const LOOK_AT = new THREE.Vector3(0, 0.6, 0);

scene.add(new THREE.HemisphereLight('#fff8ec', '#b9a27f', 1.5));
const sun = new THREE.DirectionalLight('#fff1d6', 2.2);
sun.position.set(2.5, 5, 3.5);
sun.castShadow = true;
sun.shadow.mapSize.set(1024, 1024);
Object.assign(sun.shadow.camera, { left: -2.5, right: 2.5, top: 3, bottom: -1.5, near: 1, far: 12 });
sun.shadow.bias = -0.0005;
sun.shadow.normalBias = 0.02;
scene.add(sun);

// A soft round shadow-catcher under the pot.
const floor = new THREE.Mesh(new THREE.CircleGeometry(4, 48), new THREE.ShadowMaterial({ opacity: 0.18 }));
floor.rotation.x = -Math.PI / 2;
floor.position.y = -1;
floor.receiveShadow = true;
scene.add(floor);

const plant = new PottedPlant();
scene.add(plant);
const magic = new Magic();
scene.add(magic);

let baseDistance = 6.2;
function fitCamera() {
  const aspect = window.innerWidth / window.innerHeight;
  camera.aspect = aspect;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
  // Back off on narrow screens so the whole plant stays in view.
  baseDistance = 6.2 / Math.min(1, aspect * 1.1);
}
window.addEventListener('resize', fitCamera);
fitCamera();

// A little parallax with the pointer makes the scene feel alive.
const pointer = new THREE.Vector2();
window.addEventListener('pointermove', (e) => {
  pointer.set((e.clientX / window.innerWidth) * 2 - 1, (e.clientY / window.innerHeight) * 2 - 1);
});

// ---------- steps ----------

const prevBtn = document.getElementById('prev');
const nextBtn = document.getElementById('next');
const stepEl = document.getElementById('step');
const captionEl = document.getElementById('caption');
const dotsEl = document.getElementById('dots');
document.getElementById('total').textContent = LAST_STEP;

const dots = Array.from({ length: LAST_STEP }, () => dotsEl.appendChild(document.createElement('span')));

let step = 0; // where we're going
let shown = 0; // fractional step currently on screen

function updateUI() {
  stepEl.textContent = step;
  captionEl.textContent = CAPTIONS[step];
  prevBtn.disabled = step === 0;
  nextBtn.disabled = step === LAST_STEP;
  dots.forEach((d, i) => {
    d.className = i + 1 < step ? 'done' : i + 1 === step ? 'current' : '';
  });
}

function go(delta) {
  step = Math.min(LAST_STEP, Math.max(0, step + delta));
  updateUI();
}

prevBtn.addEventListener('click', () => go(-1));
nextBtn.addEventListener('click', () => go(1));
window.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowRight') go(1);
  if (e.key === 'ArrowLeft') go(-1);
});

/** Fire the magic for step k (forwards: it happens; backwards: it is undone). */
function celebrate(k, forwards) {
  const points = plant.eventPoints(k);
  // Share ~400 sparks across the changes (fewer each when a whole bush appears at once).
  const perPoint = Math.min(90, Math.max(8, Math.round(400 / points.length)));
  for (const p of points) magic.burst(p, perPoint, !forwards);
  magic.pulse(points[0]);
}

plant.setStep(0);
updateUI();

// ---------- loop ----------

const clock = new THREE.Clock();

renderer.setAnimationLoop(() => {
  const dt = Math.min(clock.getDelta(), 0.05);
  const time = clock.elapsedTime;

  // Move towards the chosen step; hurry if several clicks are queued.
  const before = shown;
  const remaining = step - shown;
  const speed = Math.max(1, Math.abs(remaining) * 0.8) / STEP_DURATION;
  shown += Math.sign(remaining) * Math.min(Math.abs(remaining), speed * dt);

  // Step k starts when we pass k - 1 going forwards, and is undone when we pass k going back.
  if (shown > before) for (let m = Math.ceil(before); m < shown; m++) celebrate(m + 1, true);
  if (shown < before) for (let k = Math.floor(before); k > shown; k--) celebrate(k, false);

  plant.setStep(shown);
  plant.update(dt, time);
  magic.update(dt, time);

  camera.position.set(pointer.x * 0.5, 1.2 - pointer.y * 0.3, baseDistance);
  camera.lookAt(LOOK_AT);
  renderer.render(scene, camera);
});
