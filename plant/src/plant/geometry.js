import * as THREE from 'three';

export const UP = new THREE.Vector3(0, 1, 0);
const X_AXIS = new THREE.Vector3(1, 0, 0);

// ---------- easing ----------

export const clamp01 = (x) => Math.min(1, Math.max(0, x));

export function smoothstep(e0, e1, x) {
  const t = clamp01((x - e0) / (e1 - e0));
  return t * t * (3 - 2 * t);
}

export function easeOutBack(t) {
  const c1 = 1.6;
  const c3 = c1 + 1;
  return 1 + c3 * Math.pow(t - 1, 3) + c1 * Math.pow(t - 1, 2);
}

// ---------- vectors ----------

const _a = new THREE.Vector3();
const _b = new THREE.Vector3();

/** Unit vector perpendicular to `axis`, rotated by `angle` around it. */
export function perpendicular(axis, angle, out) {
  const ref = Math.abs(axis.y) < 0.95 ? UP : X_AXIS;
  _a.crossVectors(ref, axis).normalize();
  _b.crossVectors(axis, _a);
  return out.copy(_a).multiplyScalar(Math.cos(angle)).addScaledVector(_b, Math.sin(angle));
}

// ---------- sheets (leaves & petals) ----------

/**
 * Builds a grid sheet along +Z (length 0..1) spanning X, with the normal roughly +Y.
 * `shape(u, v)` gets u ∈ [0,1] along the length and v ∈ [-1,1] across, and returns [x, y, z, shade].
 */
function sheet(segU, segV, shape) {
  const positions = [];
  const colors = [];
  const indices = [];
  for (let i = 0; i <= segU; i++) {
    for (let j = 0; j <= segV; j++) {
      const [x, y, z, c] = shape(i / segU, (j / segV) * 2 - 1);
      positions.push(x, y, z);
      colors.push(c, c, c);
    }
  }
  const row = segV + 1;
  for (let i = 0; i < segU; i++) {
    for (let j = 0; j < segV; j++) {
      const a = i * row + j;
      const b = a + row;
      indices.push(a, b, a + 1, a + 1, b, b + 1);
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
  geo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
  geo.setIndex(indices);
  geo.computeVertexNormals();
  return geo;
}

export function createLeafGeometry() {
  return sheet(14, 6, (u, v) => {
    const blade = (u - 0.08) / 0.92;
    const w = u < 0.08 ? 0.02 : 0.36 * Math.pow(Math.sin(Math.PI * blade), 0.75);
    const x = v * w;
    const y = 0.9 * x * x - 0.18 * u * u; // cupped, with a slight droop
    const midrib = Math.pow(1 - Math.abs(v), 6);
    return [x, y, u, 0.72 + 0.4 * midrib];
  });
}

export function createPetalGeometry() {
  return sheet(10, 6, (u, v) => {
    const w = 0.34 * Math.pow(Math.sin(Math.PI * u), 0.7) * (0.35 + 0.65 * u);
    const x = v * w;
    const y = 0.7 * x * x + 0.12 * u * u; // cup towards the flower axis
    return [x, y, u, 0.82 + 0.3 * u];
  });
}

// ---------- tapered tube with in-place updates ----------

const _p = new THREE.Vector3();
const _t = new THREE.Vector3();
const _n = new THREE.Vector3();
const _bn = new THREE.Vector3();
const _d = new THREE.Vector3();

/** A tube whose vertex buffers are rewritten on update, so growing never allocates. */
export class Tube {
  constructor(tubular, radial) {
    this.tubular = tubular;
    this.radial = radial;
    const count = (tubular + 1) * (radial + 1);
    this.positions = new THREE.BufferAttribute(new Float32Array(count * 3), 3);
    this.normals = new THREE.BufferAttribute(new Float32Array(count * 3), 3);

    const indices = [];
    for (let i = 0; i < tubular; i++) {
      for (let j = 0; j < radial; j++) {
        const a = i * (radial + 1) + j;
        const b = a + radial + 1;
        indices.push(a, b, a + 1, b, b + 1, a + 1);
      }
    }
    this.geometry = new THREE.BufferGeometry();
    this.geometry.setAttribute('position', this.positions);
    this.geometry.setAttribute('normal', this.normals);
    this.geometry.setIndex(indices);
  }

  /** Rebuild along `curve` from 0 to `uEnd` (arc-length fraction). `radiusAt(s)` gets s ∈ [0,1] of the visible part. */
  update(curve, uEnd, radiusAt) {
    const { tubular, radial } = this;
    const pos = this.positions.array;
    const nor = this.normals.array;
    let k = 0;
    for (let i = 0; i <= tubular; i++) {
      const s = i / tubular;
      curve.getPointAt(s * uEnd, _p);
      curve.getTangentAt(s * uEnd, _t);
      if (i === 0) {
        perpendicular(_t, 0, _n);
      } else {
        // parallel transport by projection: keep the previous normal, remove the tangent component
        _n.addScaledVector(_t, -_n.dot(_t)).normalize();
      }
      _bn.crossVectors(_t, _n);
      const r = radiusAt(s);
      for (let j = 0; j <= radial; j++) {
        const ang = (j / radial) * Math.PI * 2;
        _d.copy(_n).multiplyScalar(Math.cos(ang)).addScaledVector(_bn, Math.sin(ang));
        pos[k] = _p.x + _d.x * r;
        pos[k + 1] = _p.y + _d.y * r;
        pos[k + 2] = _p.z + _d.z * r;
        nor[k] = _d.x;
        nor[k + 1] = _d.y;
        nor[k + 2] = _d.z;
        k += 3;
      }
    }
    this.positions.needsUpdate = true;
    this.normals.needsUpdate = true;
    this.geometry.computeBoundingSphere();
  }
}
