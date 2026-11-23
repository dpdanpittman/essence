// Deterministic hand-made edges. Every swatch, slip and pencil box gets its own
// edge from a seed string: the same seed always draws the same shape, two seeds
// never repeat. Pure functions, run at build time; the page ships plain SVG paths.

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

/** mulberry32: a small seeded random generator, values in [0, 1). */
export function random(seed: string): () => number {
  let a = hash(seed);
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const r1 = (n: number) => Math.round(n * 10) / 10;

/** A gentle bow plus fine tooth: the edge of paint laid with a flat brush. */
function edge(rnd: () => number, n: number, amp: number) {
  const p1 = rnd() * 6.28, f1 = 0.5 + rnd();
  let walk = 0;
  return Array.from({ length: n + 1 }, (_, i) => {
    walk = walk * 0.6 + (rnd() - 0.5) * amp * 0.9;
    return amp * 0.5 * Math.sin((i / n) * 6.28 * f1 + p1) + walk;
  });
}

/** Closed path through points, smoothed with quadratic curves through the midpoints. */
function smooth(pts: [number, number][]): string {
  const m = (a: [number, number], b: [number, number]): [number, number] => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  let d = `M${r1(m(pts[pts.length - 1], pts[0])[0])} ${r1(m(pts[pts.length - 1], pts[0])[1])}`;
  for (let i = 0; i < pts.length; i++) {
    const p = pts[i], q = m(p, pts[(i + 1) % pts.length]);
    d += `Q${r1(p[0])} ${r1(p[1])} ${r1(q[0])} ${r1(q[1])}`;
  }
  return d + 'Z';
}

/**
 * A painted swatch inside a w x h box. The long edges wobble; the two ends are
 * dry-brush ends with a few fibres. `pad` keeps the shape inside the box.
 */
export function swatchPath(seed: string, w: number, h: number, pad = 4): string {
  const rnd = random(seed);
  const horizontal = w >= h;
  const long = horizontal ? w : h, short = horizontal ? h : w;
  const n = Math.max(10, Math.round(long / 6));
  const amp = Math.min(short * 0.06, 3.2);
  const a = edge(rnd, n, amp), b = edge(rnd, n, amp);
  const ends = Math.max(5, Math.round(short / 4));
  const pts: [number, number][] = [];
  const lo = pad + amp, hi = short - pad - amp;
  // first long edge, start to end
  for (let i = 0; i <= n; i++) pts.push([pad + 2 + (i / n) * (long - 2 * pad - 4), lo + a[i]]);
  // far end: dry fibres
  for (let j = 1; j < ends; j++) {
    const fibre = rnd() < 0.3 ? amp * (1.2 + rnd() * 3.2) : rnd() * amp * 0.7;
    pts.push([long - pad - fibre, lo + (j / ends) * (hi - lo)]);
  }
  // second long edge, end to start
  for (let i = n; i >= 0; i--) pts.push([pad + 2 + (i / n) * (long - 2 * pad - 4), hi + b[i]]);
  // near end
  for (let j = ends - 1; j > 0; j--) {
    const fibre = rnd() < 0.25 ? amp * (1 + rnd() * 2.5) : rnd() * amp * 0.5;
    pts.push([pad + fibre, lo + (j / ends) * (hi - lo)]);
  }
  return smooth(horizontal ? pts : pts.map(([x, y]) => [y, x] as [number, number]));
}

/** A few thin streaks of thicker paint along the stroke, for each swatch its own. */
export function streaks(seed: string, w: number, h: number, count = 4): string {
  const rnd = random(seed + '/streaks');
  const horizontal = w >= h;
  const long = horizontal ? w : h, short = horizontal ? h : w;
  let d = '';
  for (let k = 0; k < count; k++) {
    const y = short * (0.2 + rnd() * 0.6);
    const x0 = long * (0.05 + rnd() * 0.3), x1 = long * (0.55 + rnd() * 0.4);
    const t = 0.4 + rnd() * 0.7, bend = (rnd() - 0.5) * short * 0.12;
    const pts = horizontal
      ? `M${r1(x0)} ${r1(y)}Q${r1((x0 + x1) / 2)} ${r1(y + bend)} ${r1(x1)} ${r1(y)}L${r1(x1)} ${r1(y + t)}Q${r1((x0 + x1) / 2)} ${r1(y + bend + t)} ${r1(x0)} ${r1(y + t)}Z`
      : `M${r1(y)} ${r1(x0)}Q${r1(y + bend)} ${r1((x0 + x1) / 2)} ${r1(y)} ${r1(x1)}L${r1(y + t)} ${r1(x1)}Q${r1(y + bend + t)} ${r1((x0 + x1) / 2)} ${r1(y + t)} ${r1(x0)}Z`;
    d += pts;
  }
  return d;
}

/** A rectangle drawn in pencil: four separate lines that overshoot the corners a little. */
export function pencilBox(seed: string, w: number, h: number, pad = 3): string {
  const rnd = random(seed);
  const j = () => (rnd() - 0.5) * 2.2;
  const o = () => 1 + rnd() * 4;
  const L = pad, T = pad, R = w - pad, B = h - pad;
  const line = (x0: number, y0: number, x1: number, y1: number) => {
    const mx = (x0 + x1) / 2 + j(), my = (y0 + y1) / 2 + j();
    return `M${r1(x0)} ${r1(y0)}Q${r1(mx)} ${r1(my)} ${r1(x1)} ${r1(y1)}`;
  };
  return (
    line(L - o(), T + j(), R + o(), T + j()) +
    line(R + j(), T - o(), R + j(), B + o()) +
    line(R + o(), B + j(), L - o(), B + j()) +
    line(L + j(), B + o(), L + j(), T - o())
  );
}

/** A torn bottom edge for a slip of paper, as a CSS polygon in percent. */
export function tornPolygon(seed: string, teeth = 28): string {
  const rnd = random(seed);
  const pts = ['0% 0%', '100% 0%'];
  for (let i = teeth; i >= 0; i--) {
    const x = (i / teeth) * 100;
    const y = 100 - rnd() * 3.2 - (i % 2 ? 0.8 : 0);
    pts.push(`${r1(x)}% ${r1(y)}%`);
  }
  return `polygon(${pts.join(', ')})`;
}

/** A hand-drawn underline, w wide. */
export function pencilLine(seed: string, w: number): string {
  const rnd = random(seed);
  const y = () => 4 + (rnd() - 0.5) * 2.5;
  return `M1 ${r1(y())}C${r1(w * 0.3)} ${r1(y())} ${r1(w * 0.6)} ${r1(y())} ${r1(w - 1)} ${r1(y())}`;
}
