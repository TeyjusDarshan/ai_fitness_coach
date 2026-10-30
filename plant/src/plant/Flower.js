import * as THREE from 'three';
import { UP, createPetalGeometry, easeOutBack, perpendicular, smoothstep } from './geometry.js';

const PETALS = 6;
const GREEN = new THREE.Color('#6f9a3a');
const GLOW = new THREE.Color('#ffd27a');

const petalGeometry = createPetalGeometry();
const sphere = new THREE.SphereGeometry(1, 16, 12);

const _side = new THREE.Vector3();
const _fwd = new THREE.Vector3();
const _nrm = new THREE.Vector3();
const _x = new THREE.Vector3();
const _m = new THREE.Matrix4();

/**
 * One flower, from bud to open bloom. Built in a local frame whose +Y is the flower's axis.
 * `bud` (0..1) is how swollen the bud is; `bloom` (0..1) is how open the petals are.
 */
export class Flower extends THREE.Group {
  constructor({ color, size }) {
    super();
    this.size = size;
    this.color = new THREE.Color(color);

    this.petalMaterial = new THREE.MeshStandardMaterial({ side: THREE.DoubleSide, roughness: 0.5, vertexColors: true });
    this.budMaterial = new THREE.MeshStandardMaterial({ color: GREEN, roughness: 0.7 });
    this.centerMaterial = new THREE.MeshStandardMaterial({ color: '#ffd23f', roughness: 0.8 });

    this.bud = new THREE.Mesh(sphere, this.budMaterial);
    this.center = new THREE.Mesh(sphere, this.centerMaterial);
    this.petals = Array.from({ length: PETALS }, () => {
      const petal = new THREE.Mesh(petalGeometry, this.petalMaterial);
      petal.matrixAutoUpdate = false;
      return petal;
    });
    this.add(this.bud, this.center, ...this.petals);
    this.bud.castShadow = true; // petals skip shadows to keep the full bush light
    this.visible = false;
  }

  /** Place the flower at `position`, facing along `axis`. */
  place(position, axis) {
    this.position.copy(position);
    this.quaternion.setFromUnitVectors(UP, axis);
  }

  set(bud, bloom, glow) {
    this.visible = bud > 0.001;
    if (!this.visible) return;
    const { size } = this;
    const grow = easeOutBack(bud);

    // Green bud that shrinks back into a cup as the petals open.
    const budR = size * 0.26 * grow * (1 - 0.45 * bloom);
    this.bud.scale.set(budR * 0.8, budR * 1.1, budR * 0.8);
    this.bud.position.y = budR * 0.7;

    // Petals: a closed coloured tip on the bud that unfolds to a flat, open flower.
    const open = smoothstep(0, 1, bloom);
    const len = size * (0.5 + 0.5 * easeOutBack(bloom)) * grow;
    const theta = 0.12 + 1.3 * open;
    for (let k = 0; k < PETALS; k++) {
      perpendicular(UP, (k / PETALS) * Math.PI * 2, _side);
      _fwd.copy(UP).multiplyScalar(Math.cos(theta)).addScaledVector(_side, Math.sin(theta));
      _nrm.copy(UP).addScaledVector(_fwd, -_fwd.y).normalize();
      _x.crossVectors(_nrm, _fwd);
      _m.makeBasis(_x, _nrm, _fwd).scale(_side.set(len, len, len)).setPosition(0, budR * 0.9, 0);
      this.petals[k].matrix.copy(_m);
    }
    this.petalMaterial.color.lerpColors(GREEN, this.color, 0.45 + 0.55 * open);

    const c = size * 0.2 * easeOutBack(smoothstep(0.3, 1, bloom));
    this.center.visible = c > 0.001;
    this.center.scale.set(c, c * 0.55, c);
    this.center.position.y = budR * 0.9 + size * 0.04;

    for (const mat of [this.petalMaterial, this.budMaterial, this.centerMaterial]) {
      mat.emissive.copy(GLOW).multiplyScalar(glow);
    }
  }
}
