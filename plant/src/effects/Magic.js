import * as THREE from 'three';

const MAX_SPARKS = 600;
const PALETTE = ['#ffd84d', '#ffb238', '#ff6fb5', '#b07cff', '#fff6c8'].map((c) => new THREE.Color(c));

function sparkTexture() {
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, 'rgba(255,255,255,1)');
  g.addColorStop(0.25, 'rgba(255,255,255,0.8)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, size, size);
  // A thin four-pointed star on top of the glow.
  ctx.fillStyle = 'rgba(255,255,255,0.9)';
  ctx.fillRect(size / 2 - 1, 4, 2, size - 8);
  ctx.fillRect(4, size / 2 - 1, size - 8, 2);
  return new THREE.CanvasTexture(canvas);
}

/**
 * The "magic" of each transformation: swirling sparkles where something changes,
 * a ring of light rising from the pot, and a soft flash.
 */
export class Magic extends THREE.Group {
  constructor() {
    super();
    this.positions = new Float32Array(MAX_SPARKS * 3);
    this.colors = new Float32Array(MAX_SPARKS * 4); // RGBA: alpha fades each spark out completely
    this.sparks = Array.from({ length: MAX_SPARKS }, () => ({
      life: 0,
      maxLife: 1,
      center: new THREE.Vector3(),
      angle: 0,
      spin: 0,
      radius: 0,
      spread: 0,
      rise: 0,
      color: new THREE.Color(),
    }));
    this.next = 0;

    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(this.positions, 3).setUsage(THREE.DynamicDrawUsage));
    geo.setAttribute('color', new THREE.BufferAttribute(this.colors, 4).setUsage(THREE.DynamicDrawUsage));
    this.points = new THREE.Points(
      geo,
      new THREE.PointsMaterial({
        size: 0.11,
        map: sparkTexture(),
        vertexColors: true,
        transparent: true,
        depthWrite: false,
      }),
    );
    this.points.frustumCulled = false;
    this.add(this.points);

    this.ring = new THREE.Mesh(
      new THREE.RingGeometry(0.62, 0.7, 64),
      new THREE.MeshBasicMaterial({ color: '#ffd27a', transparent: true, opacity: 0, depthWrite: false, side: THREE.DoubleSide }),
    );
    this.ring.rotation.x = -Math.PI / 2;
    this.ringLife = 0;
    this.add(this.ring);

    // Always in the scene (intensity 0 when idle) so shaders never need recompiling.
    this.light = new THREE.PointLight('#ffd98a', 0, 5, 1.5);
    this.flash = 0;
    this.add(this.light);
  }

  /** A swirl of sparkles around `point`. `gentle` is used when undoing a step. */
  burst(point, count = 40, gentle = false) {
    for (let i = 0; i < count; i++) {
      const s = this.sparks[this.next];
      this.next = (this.next + 1) % MAX_SPARKS;
      s.maxLife = s.life = (gentle ? 0.8 : 1.1) + Math.random() * 0.8;
      s.center.copy(point);
      s.angle = Math.random() * Math.PI * 2;
      s.spin = (Math.random() < 0.5 ? -1 : 1) * (2 + Math.random() * 3);
      s.radius = Math.random() * 0.05;
      s.spread = (gentle ? 0.2 : 0.35) + Math.random() * 0.35;
      s.rise = (gentle ? -0.1 : 0.25) + Math.random() * 0.5;
      s.color.copy(gentle ? PALETTE[3] : PALETTE[Math.floor(Math.random() * PALETTE.length)]);
    }
  }

  /** The ring of light and the flash that go with every step. */
  pulse(center) {
    this.ringLife = 1;
    this.flash = 1;
    this.light.position.copy(center).add(new THREE.Vector3(0, 0.2, 0.6));
  }

  update(dt, time) {
    const pos = this.positions;
    const col = this.colors;
    this.sparks.forEach((s, i) => {
      const k = i * 3;
      const c = i * 4;
      if (s.life <= 0) {
        col[c + 3] = 0; // fully transparent once spent
        return;
      }
      s.life = Math.max(0, s.life - dt);
      const age = 1 - s.life / s.maxLife; // 0 → 1
      s.angle += s.spin * dt;
      const r = s.radius + s.spread * Math.sqrt(age);
      pos[k] = s.center.x + Math.cos(s.angle) * r;
      pos[k + 1] = s.center.y + s.rise * age;
      pos[k + 2] = s.center.z + Math.sin(s.angle) * r;
      // Fade in quickly, twinkle, and fade out to nothing by the end of its life.
      const fade = Math.max(0, Math.sin(Math.PI * age)) * (0.75 + 0.25 * Math.sin(time * 25 + i));
      col[c] = s.color.r;
      col[c + 1] = s.color.g;
      col[c + 2] = s.color.b;
      col[c + 3] = s.life > 0 ? fade : 0;
    });
    this.points.geometry.attributes.position.needsUpdate = true;
    this.points.geometry.attributes.color.needsUpdate = true;

    if (this.ringLife > 0) {
      this.ringLife = Math.max(0, this.ringLife - dt * 0.9);
      const age = 1 - this.ringLife;
      this.ring.scale.setScalar(1 + age * 1.4);
      this.ring.position.y = 0.12 + age * 0.8;
      this.ring.material.opacity = 0.8 * this.ringLife;
    }
    this.ring.visible = this.ringLife > 0;

    this.flash = Math.max(0, this.flash - dt * 1.2);
    this.light.intensity = 4 * Math.sin(Math.PI * Math.min(1, (1 - this.flash) * 1.2)) * (this.flash > 0 ? 1 : 0);
  }
}
