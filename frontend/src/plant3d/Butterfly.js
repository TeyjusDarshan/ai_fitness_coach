import * as THREE from 'three';
import { easeOutBack } from './geometry.js';

const _prev = new THREE.Vector3();
const _target = new THREE.Vector3();

function createWingGeometry() {
  const s = new THREE.Shape();
  s.moveTo(0, 0);
  s.bezierCurveTo(0.25, 0.4, 0.75, 0.42, 0.72, 0.08);
  s.bezierCurveTo(0.7, -0.12, 0.42, -0.5, 0.14, -0.42);
  s.lineTo(0, 0);
  const geo = new THREE.ShapeGeometry(s, 10);
  geo.rotateX(Math.PI / 2); // lie flat, forewing pointing forward (+Z)
  geo.scale(0.26, 0.26, 0.26);
  return geo;
}
const wingGeometry = createWingGeometry();
const bodyGeometry = new THREE.CapsuleGeometry(0.016, 0.13, 2, 6).rotateX(Math.PI / 2);

/**
 * A butterfly that keeps fluttering in loops around the front of the bush.
 * Its path stays on the camera side (+Z) so it never hides behind the plant.
 */
export class Butterfly extends THREE.Group {
  constructor({ color, phase, home }) {
    super();
    this.phase = phase;
    this.home = home.clone();
    this.pos = home.clone();
    this.heading = 0;

    const wingMat = new THREE.MeshStandardMaterial({
      color,
      side: THREE.DoubleSide,
      roughness: 0.45,
      emissive: color,
      emissiveIntensity: 0.2,
    });
    this.right = new THREE.Mesh(wingGeometry, wingMat);
    this.left = new THREE.Mesh(wingGeometry, wingMat);
    this.left.scale.x = -1;
    const body = new THREE.Mesh(bodyGeometry, new THREE.MeshStandardMaterial({ color: '#2b2118' }));
    this.body = new THREE.Group();
    this.body.rotation.order = 'YXZ';
    this.body.add(this.right, this.left, body);
    for (const m of [this.right, this.left]) m.castShadow = true;
    this.add(this.body);
    this.visible = false;
  }

  /** Point on a looping path through the air in front of the bush. */
  pathPoint(time, out) {
    const t = time + this.phase * 7;
    return out.set(
      1.4 * Math.sin(t * 0.45),
      1.75 + 0.45 * Math.sin(t * 0.9 + this.phase),
      1.4 + 0.25 * Math.sin(t * 0.6 + this.phase * 2),
    );
  }

  /** `presence` 0..1 makes it appear (or vanish when going back a step). */
  update(dt, time, presence) {
    this.visible = presence > 0.001;
    if (!this.visible) {
      this.pos.copy(this.home);
      return;
    }
    this.scale.setScalar(easeOutBack(presence));

    // Always on the wing: chase a point moving along the loop, with a fluttery bob.
    this.pathPoint(time, _target);
    _prev.copy(this.pos);
    this.pos.lerp(_target, Math.min(1, dt * 1.6));
    this.position.copy(this.pos);
    this.position.y += Math.sin(time * 7 + this.phase) * 0.04;

    const dx = this.pos.x - _prev.x;
    const dz = this.pos.z - _prev.z;
    if (Math.hypot(dx, dz) > 1e-4) {
      const delta = Math.atan2(dx, dz) - this.heading;
      this.heading += Math.atan2(Math.sin(delta), Math.cos(delta)) * Math.min(1, dt * 6);
    }
    this.body.rotation.y = this.heading;

    const flap = 0.3 + 0.9 * Math.sin(time * 22 + this.phase * 3);
    this.right.rotation.z = flap;
    this.left.rotation.z = -flap;
  }
}
