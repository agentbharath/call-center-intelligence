import React, { useState, useRef, useEffect, useCallback } from "react";

/* ------------------------------------------------------------------ */
/*  Skin Readout — capture a face photo, check pose, read the skin.    */
/* ------------------------------------------------------------------ */

const METRIC_ORDER = ["Hydration", "Texture", "Even tone", "Pores", "Redness", "Shine"];

/* Plain-language definitions, surfaced on hover and on focus. */
const GLOSS = {
  Yaw: "Which way your head is turned, left or right. 0 degrees means you are facing the camera square on.",
  Pitch: "How far your chin is raised or dropped. 0 degrees means your head is level.",
  Roll: "How far your head is tilted toward one shoulder. 0 degrees means upright.",
  Hydration:
    "How plump and light-reflective the skin looks. Skin short on water looks dull and flat, and fine lines show up more.",
  Texture:
    "How smooth the surface looks close up. Bumps, flaking and rough patches push this down.",
  "Even tone":
    "How uniform the colour is across the face. Patchiness, dark marks left by old spots, and blotchy areas push this down.",
  Pores:
    "How visible the small openings in the skin are, mostly around the nose and inner cheeks. Higher score means less visible.",
  Redness:
    "How much visible flushing or pink patching there is. Higher score means less redness.",
  Shine:
    "How much light bounces straight off the surface. It stands in for oil sitting on the skin at this moment, which changes through the day.",
  "T-zone":
    "Your forehead, the strip between the brows, and the nose. Together they form a T, and they are usually the first areas to go oily.",
  "Under-eye":
    "The soft skin from the lower lash line down onto the top of the cheek, where darkness and puffiness show first.",
  "Surface score":
    "An even average of the six measures below. It describes this one photo under this one light, not your skin overall.",
  "Skin type":
    "A rough sort into oily, dry, combination or normal, based on where shine and dryness show up on the face.",
  "Apparent skin age":
    "A guess at how old the skin surface looks, from texture, evenness and fine lines only. It is not an estimate of your actual age, and it swings widely with lighting and camera.",
  Confidence:
    "How much weight to put on this reading, based on how sharp, well lit and well framed the photo is. Poor capture hits texture and pore scores hardest.",
  Mesh:
    "A wireframe built from face points the model marks in the photo. It is an approximation, not a precise 468-point face tracker.",
  Zones:
    "The mesh shaded by each area's score. Darker means the area scored lower.",
  Reticle:
    "A crosshair that leans and shifts to match the head angle detected in the photo.",
  Spread:
    "The gap between the highest and lowest score across repeat readings of the same photo. A wide spread means the model is unsure.",
};

/* Landmark names the model is asked to place, and the wireframe drawn over them. */
const TRIS = [
  ["hair", "temple_l", "brow_l", "Forehead"],
  ["hair", "brow_l", "nose_top", "Forehead"],
  ["hair", "nose_top", "brow_r", "Forehead"],
  ["hair", "brow_r", "temple_r", "Forehead"],
  ["brow_l", "eye_l", "nose_top", "Under-eye"],
  ["brow_l", "eye_l_out", "eye_l", "Under-eye"],
  ["temple_l", "brow_l", "eye_l_out", "Under-eye"],
  ["brow_r", "nose_top", "eye_r", "Under-eye"],
  ["brow_r", "eye_r", "eye_r_out", "Under-eye"],
  ["temple_r", "eye_r_out", "brow_r", "Under-eye"],
  ["eye_l_out", "eye_l", "cheek_l", "Under-eye"],
  ["eye_r", "eye_r_out", "cheek_r", "Under-eye"],
  ["eye_l", "nose_top", "nose_tip", "T-zone"],
  ["nose_top", "eye_r", "nose_tip", "T-zone"],
  ["eye_l", "nose_tip", "cheek_l", "Cheeks"],
  ["eye_r", "nose_tip", "cheek_r", "Cheeks"],
  ["temple_l", "eye_l_out", "cheek_l", "Cheeks"],
  ["temple_r", "cheek_r", "eye_r_out", "Cheeks"],
  ["cheek_l", "nose_tip", "mouth_l", "Cheeks"],
  ["cheek_r", "mouth_r", "nose_tip", "Cheeks"],
  ["nose_tip", "mouth_c", "mouth_l", "T-zone"],
  ["nose_tip", "mouth_r", "mouth_c", "T-zone"],
  ["cheek_l", "mouth_l", "jaw_l", "Jaw and chin"],
  ["mouth_l", "chin", "jaw_l", "Jaw and chin"],
  ["mouth_l", "mouth_c", "chin", "Jaw and chin"],
  ["mouth_c", "mouth_r", "chin", "Jaw and chin"],
  ["mouth_r", "jaw_r", "chin", "Jaw and chin"],
  ["cheek_r", "jaw_r", "mouth_r", "Jaw and chin"],
];

/* Stage one asks only for a coarse box. Models are far better at "roughly
   where is the face" than at "place nineteen points precisely", so we crop
   to the box and ask for landmarks inside a frame the face actually fills. */
const BOX_PROMPT = `Look at this photo and find the single most prominent human face.

Return ONLY this JSON, no fences, no other text:
{ "box": [x, y, w, h], "found": true }

box is the tight rectangle around the face only, as fractions of image width and height, top-left origin. Top edge at the hairline, bottom edge at the lowest point of the chin, left and right edges at the outer edges of the cheeks or ears. Do not include neck, shoulders, hair above the hairline, or background. If no face is visible, set found to false and box to null.`;

const PROMPT = `You are the analysis engine for a consumer grooming app that reads skin appearance from a photo.

Report ONLY on visible cosmetic appearance. Never diagnose, name, or hint at a medical or dermatological condition. If anything looks like it deserves professional attention, the only thing you may say is "worth showing to a dermatologist" inside the watch array.

Return ONLY a JSON object. No markdown fences, no preamble, no trailing text. Exact shape:

{
  "face": { "detected": true, "count": 1 },
  "capture": { "lighting": 0, "sharpness": 0, "framing": 0, "flag": "" },
  "pose": { "label": "", "yaw": 0, "pitch": 0, "roll": 0, "usable": true, "fix": "" },
  "lm": { "hair": [0,0], "temple_l": [0,0], "temple_r": [0,0], "brow_l": [0,0], "brow_r": [0,0], "eye_l": [0,0], "eye_r": [0,0], "eye_l_out": [0,0], "eye_r_out": [0,0], "nose_top": [0,0], "nose_tip": [0,0], "cheek_l": [0,0], "cheek_r": [0,0], "mouth_l": [0,0], "mouth_r": [0,0], "mouth_c": [0,0], "jaw_l": [0,0], "jaw_r": [0,0], "chin": [0,0] },
  "skin": {
    "score": 0,
    "type": "",
    "age": 0,
    "metrics": [ { "k": "Hydration", "v": 0, "note": "" } ],
    "zones": [ { "z": "Forehead", "v": 0, "note": "" } ],
    "watch": [ "" ],
    "next": [ "" ]
  }
}

Rules:
- All scores are integers 0-100, where 100 is the best possible appearance. For Redness and Shine, 100 means minimal redness and minimal shine.
- metrics: exactly these six k values in order: Hydration, Texture, Even tone, Pores, Redness, Shine.
- zones: exactly these five z values in order: Forehead, T-zone, Cheeks, Under-eye, Jaw and chin. Each carries its own 0-100 score in v.
- lm holds every listed point as [x, y] fractions of image width and height, 0 to 1, top-left origin. This image is cropped tightly around the face, so the face fills nearly the whole frame: hair should sit near the top edge, chin near the bottom edge, and the jaw points near the left and right edges. Use the full 0 to 1 range. _l is the left side of the image as you look at it, _r the right. hair is the centre of the hairline, temple points sit at the widest part of the brow line, jaw points at the widest part of the jaw, chin at the lowest point. Read the actual pixels rather than assuming standard proportions.
- pose.yaw is head turn in degrees, negative toward the left edge. pose.pitch is nod, negative for chin down. pose.roll is tilt, negative toward the left edge. pose.label is 2-4 words.
- pose.usable is false only if the angle or crop makes the skin hard to read. pose.fix is one short instruction, or "".
- capture.flag is one short note about lighting, blur or crop, or "".
- skin.type is one of: oily, dry, combination, normal.
- skin.age is a whole number between 15 and 80: roughly how old the skin surface looks, judged on texture, evenness and fine lines alone. It is a guess about appearance, not about the person.
- Every note is 10 words or fewer, plain language, describing what you can actually see.
- watch holds 0-2 short items. next holds exactly 3 short, practical grooming steps.
- If no human face is visible, set face.detected to false and set both "lm" and "skin" to null.`;

const MAX_EDGE = 1100;

function toPayload(source, w, h) {
  const scale = Math.min(1, MAX_EDGE / Math.max(w, h));
  const c = document.createElement("canvas");
  c.width = Math.round(w * scale);
  c.height = Math.round(h * scale);
  c.getContext("2d").drawImage(source, 0, 0, c.width, c.height);
  const dataUrl = c.toDataURL("image/jpeg", 0.9);
  return { dataUrl, base64: dataUrl.split(",")[1], w: c.width, h: c.height };
}

function prepImage(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("That file could not be read. Try another photo."));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("That file is not an image the app can open."));
      img.onload = () => resolve(toPayload(img, img.width, img.height));
      img.src = reader.result;
    };
    reader.readAsDataURL(file);
  });
}

const clamp01 = (n) => Math.max(0, Math.min(1, n));

function loadImg(src) {
  return new Promise((res, rej) => {
    const i = new Image();
    i.onload = () => res(i);
    i.onerror = () => rej(new Error("Could not reopen the frame."));
    i.src = src;
  });
}

function cropTo(img, box) {
  const sx = box[0] * img.width;
  const sy = box[1] * img.height;
  const sw = box[2] * img.width;
  const sh = box[3] * img.height;
  const scale = Math.min(1, 900 / Math.max(sw, sh));
  const c = document.createElement("canvas");
  c.width = Math.round(sw * scale);
  c.height = Math.round(sh * scale);
  c.getContext("2d").drawImage(img, sx, sy, sw, sh, 0, 0, c.width, c.height);
  const dataUrl = c.toDataURL("image/jpeg", 0.92);
  return { dataUrl, base64: dataUrl.split(",")[1] };
}

/* A face has fixed proportions. If the returned points break them, the model
   drew a template instead of reading the photo, and a wrong mesh is worse
   than no mesh, so we drop it rather than show it. */
function meshIsSane(lm) {
  if (!lm) return false;
  const need = ["hair", "chin", "eye_l", "eye_r", "nose_tip", "mouth_c", "jaw_l", "jaw_r"];
  for (const k of need) {
    const p = lm[k];
    if (!Array.isArray(p) || p.length < 2) return false;
    if (p[0] < -0.08 || p[0] > 1.08 || p[1] < -0.08 || p[1] > 1.08) return false;
  }
  const dx = lm.eye_r[0] - lm.eye_l[0];
  const dy = lm.eye_r[1] - lm.eye_l[1];
  const inter = Math.hypot(dx, dy);
  if (inter < 0.08) return false; // eyes collapsed together
  if (lm.eye_l[0] >= lm.eye_r[0]) return false; // sides swapped
  // features must stack in the right order down the face
  const eyeY = (lm.eye_l[1] + lm.eye_r[1]) / 2;
  if (!(lm.hair[1] < eyeY && eyeY < lm.nose_tip[1] && lm.nose_tip[1] < lm.mouth_c[1] && lm.mouth_c[1] < lm.chin[1]))
    return false;
  // hairline to chin runs about 2 to 4.5 times the pupil gap on a real face
  const faceH = Math.abs(lm.chin[1] - lm.hair[1]);
  const r = faceH / inter;
  if (r < 1.8 || r > 4.8) return false;
  // jaw width sits near 1.4 to 3.2 times the pupil gap
  const jawW = Math.abs(lm.jaw_r[0] - lm.jaw_l[0]);
  const jr = jawW / inter;
  if (jr < 1.2 || jr > 3.4) return false;
  return true;
}

const median = (arr) => {
  const s = arr.filter((n) => typeof n === "number" && !isNaN(n)).sort((a, b) => a - b);
  if (!s.length) return 0;
  const m = Math.floor(s.length / 2);
  return s.length % 2 ? s[m] : Math.round((s[m - 1] + s[m]) / 2);
};
const spread = (arr) => {
  const s = arr.filter((n) => typeof n === "number" && !isNaN(n));
  return s.length > 1 ? Math.round((Math.max(...s) - Math.min(...s)) / 2) : 0;
};

/* ------------------------------ pieces ----------------------------- */

/* A term with its meaning attached. Works on hover, on keyboard focus,
   and on tap, because a hover-only tooltip is useless on a phone. */
function Term({ children, k }) {
  const [open, setOpen] = useState(false);
  const def = GLOSS[k || children];
  if (!def) return <>{children}</>;
  return (
    <span className="term-wrap">
      <button
        type="button"
        className="term"
        aria-label={`${k || children}: ${def}`}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
      >
        {children}
      </button>
      {open ? (
        <span className="tip" role="tooltip">
          <span className="tip-k">{k || children}</span>
          {def}
        </span>
      ) : null}
    </span>
  );
}

function Meter({ name, value, note, band, delay }) {
  const v = Math.max(0, Math.min(100, Number(value) || 0));
  return (
    <div className="meter" style={{ animationDelay: `${delay}ms` }}>
      <div className="meter-head">
        <span className="meter-name">
          <Term>{name}</Term>
        </span>
        <span className="meter-val">
          {v}
          {band ? <em className="meter-band">&plusmn;{band}</em> : null}
        </span>
      </div>
      <div className="meter-track">
        <div className="meter-fill" style={{ width: `${v}%` }} />
        {band ? (
          <div
            className="meter-spread"
            style={{ left: `${Math.max(0, v - band)}%`, width: `${Math.min(100, band * 2)}%` }}
          />
        ) : null}
        <div className="meter-needle" style={{ left: `${v}%` }} />
      </div>
      {note ? <p className="meter-note">{note}</p> : null}
    </div>
  );
}

function Axis({ label, value, range }) {
  const v = Math.max(-range, Math.min(range, Number(value) || 0));
  const pos = 50 + (v / range) * 50;
  return (
    <div className="axis">
      <span className="axis-label">
        <Term>{label}</Term>
      </span>
      <div className="axis-track">
        <div className="axis-zero" />
        <div className="axis-dot" style={{ left: `${pos}%` }} />
      </div>
      <span className="axis-val">
        {v > 0 ? `+${v}` : v}&deg;
      </span>
    </div>
  );
}

function Reticle({ pose }) {
  const roll = Math.max(-30, Math.min(30, pose?.roll || 0));
  const yaw = Math.max(-45, Math.min(45, pose?.yaw || 0));
  const pitch = Math.max(-35, Math.min(35, pose?.pitch || 0));
  return (
    <div className="reticle" style={{ transform: `rotate(${roll}deg)` }} aria-hidden="true">
      <span className="r-corner tl" />
      <span className="r-corner tr" />
      <span className="r-corner bl" />
      <span className="r-corner br" />
      <span className="r-v" style={{ left: `${50 + yaw * 0.5}%` }} />
      <span className="r-h" style={{ top: `${50 - pitch * 0.6}%` }} />
    </div>
  );
}

/* Wireframe over the face, optionally shaded by each zone's score. */
function Mesh({ lm, zoneScores, shaded }) {
  if (!lm) return null;
  const p = (n) => {
    const pt = lm[n];
    if (!Array.isArray(pt) || pt.length < 2) return null;
    return [pt[0] * 100, pt[1] * 100];
  };
  const tint = (zone) => {
    if (!shaded) return "rgba(124,77,255,0.07)";
    const s = zoneScores[zone];
    if (typeof s !== "number") return "rgba(124,77,255,0.07)";
    const a = (0.62 - (s / 100) * 0.55).toFixed(3);
    return `rgba(124,77,255,${a})`;
  };
  const tris = TRIS.map((t, i) => {
    const pts = [p(t[0]), p(t[1]), p(t[2])];
    if (pts.some((x) => !x)) return null;
    return (
      <polygon
        key={i}
        points={pts.map((x) => `${x[0]},${x[1]}`).join(" ")}
        fill={tint(t[3])}
        stroke="rgba(160,120,255,0.85)"
        strokeWidth="0.22"
        vectorEffect="non-scaling-stroke"
      />
    );
  }).filter(Boolean);

  return (
    <svg className="mesh" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      {tris}
      {Object.keys(lm).map((n) => {
        const pt = p(n);
        return pt ? <circle key={n} cx={pt[0]} cy={pt[1]} r="0.55" fill="#C9B6FF" /> : null;
      })}
    </svg>
  );
}

/* Where each callout points. Landmarks when they passed the sanity check,
   otherwise proportions inside the face box from pass one, otherwise a
   centred guess. The poster degrades instead of breaking. */
const CALLOUTS = [
  { k: "Hydration", a: "forehead", side: "left", t: 0.14 },
  { k: "Redness", a: "cheek_l", side: "left", t: 0.45 },
  { k: "Texture", a: "jaw_l", side: "left", t: 0.76 },
  { k: "Shine", a: "nose_top", side: "right", t: 0.22 },
  { k: "Even tone", a: "cheek_r", side: "right", t: 0.53 },
  { k: "Pores", a: "nose_tip", side: "right", t: 0.84 },
];

const BOX_FRACTIONS = {
  forehead: [0.5, 0.22],
  cheek_l: [0.28, 0.55],
  cheek_r: [0.72, 0.55],
  nose_top: [0.5, 0.4],
  nose_tip: [0.5, 0.53],
  jaw_l: [0.3, 0.75],
  chin: [0.5, 0.86],
};

function anchorsFrom(lm, ok, box) {
  if (ok && lm) {
    const browY = (lm.brow_l[1] + lm.brow_r[1]) / 2;
    return {
      forehead: [(lm.hair[0] + lm.brow_l[0] + lm.brow_r[0]) / 3, (lm.hair[1] + browY) / 2],
      cheek_l: lm.cheek_l,
      cheek_r: lm.cheek_r,
      nose_top: lm.nose_top,
      nose_tip: lm.nose_tip,
      jaw_l: lm.jaw_l,
      chin: lm.chin,
    };
  }
  const b = box || [0.2, 0.1, 0.6, 0.8];
  const out = {};
  Object.keys(BOX_FRACTIONS).forEach((k) => {
    const f = BOX_FRACTIONS[k];
    out[k] = [b[0] + f[0] * b[2], b[1] + f[1] * b[3]];
  });
  return out;
}

function Poster({ image, result, meshOk }) {
  const svgRef = useRef(null);
  const [saving, setSaving] = useState("");
  const skin = result?.skin;
  if (!skin) return null;

  const W = image.w;
  const H = image.h;
  const G = W * 0.46;
  const BOT = W * 0.17;
  const vbX = -G;
  const vbW = W + 2 * G;
  const vbH = H + BOT;

  const fs = W * 0.038;
  const fsNum = W * 0.034;
  const anchors = anchorsFrom(result.lm, meshOk, result.box);
  const byKey = {};
  (skin.metrics || []).forEach((m) => {
    byKey[m.k] = m.v;
  });

  const lm = result.lm;
  const midX = meshOk && lm ? ((lm.nose_top[0] + lm.chin[0]) / 2) * W : W / 2;

  const save = async () => {
    setSaving("working");
    try {
      const src = new XMLSerializer().serializeToString(svgRef.current);
      const blob = new Blob([src], { type: "image/svg+xml;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const img = await loadImg(url);
      const c = document.createElement("canvas");
      c.width = Math.round(vbW * 2);
      c.height = Math.round(vbH * 2);
      c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(url);
      const a = document.createElement("a");
      a.download = "skin-readout.png";
      a.href = c.toDataURL("image/png");
      a.click();
      setSaving("");
    } catch (e) {
      setSaving("failed");
    }
  };

  return (
    <div className="poster">
      <svg
        ref={svgRef}
        xmlns="http://www.w3.org/2000/svg"
        viewBox={`${vbX} 0 ${vbW} ${vbH}`}
        style={{ width: "100%", height: "auto", display: "block" }}
      >
        <rect x={vbX} y={0} width={vbW} height={vbH} fill="#0D0F13" />
        <image href={image.dataUrl} x={0} y={0} width={W} height={H} preserveAspectRatio="none" />

        {/* mesh, only when the points survived the geometry check */}
        {meshOk && lm
          ? TRIS.map((t, i) => {
              const pts = [t[0], t[1], t[2]].map((n) => lm[n]);
              if (pts.some((p) => !Array.isArray(p))) return null;
              return (
                <polygon
                  key={i}
                  points={pts.map((p) => `${p[0] * W},${p[1] * H}`).join(" ")}
                  fill="rgba(255,255,255,0.04)"
                  stroke="rgba(255,255,255,0.55)"
                  strokeWidth={W * 0.0016}
                />
              );
            })
          : null}
        {meshOk && lm
          ? Object.keys(lm).map((n) => (
              <circle key={n} cx={lm[n][0] * W} cy={lm[n][1] * H} r={W * 0.005} fill="#fff" />
            ))
          : null}

        {/* the midline the pose angles are measured against */}
        <line x1={midX} y1={0} x2={midX} y2={H} stroke="#FF4438" strokeWidth={W * 0.004} opacity="0.75" />

        {/* callouts */}
        {CALLOUTS.map((c) => {
          const v = byKey[c.k];
          if (typeof v !== "number") return null;
          const p = anchors[c.a];
          if (!p) return null;
          const ax = p[0] * W;
          const ay = p[1] * H;
          const isL = c.side === "left";
          const lx = isL ? vbX + W * 0.05 : W + G - W * 0.05;
          const y = H * c.t;
          const ruleY = y + fs * 1.55;
          const ruleEnd = isL ? lx + W * 0.33 : lx - W * 0.33;
          const bend = isL ? ruleEnd + W * 0.05 : ruleEnd - W * 0.05;
          return (
            <g key={c.k}>
              <text
                x={lx}
                y={y}
                fill="#F3F4F6"
                fontFamily="IBM Plex Sans, Helvetica, Arial, sans-serif"
                fontSize={fs}
                fontWeight="500"
                textAnchor={isL ? "start" : "end"}
              >
                {c.k}
              </text>
              <text
                x={lx}
                y={y + fs * 1.15}
                fill="#B79CFF"
                fontFamily="IBM Plex Mono, monospace"
                fontSize={fsNum}
                textAnchor={isL ? "start" : "end"}
              >
                {v} / 100
              </text>
              <polyline
                points={`${lx},${ruleY} ${ruleEnd},${ruleY} ${bend},${ruleY} ${ax},${ay}`}
                fill="none"
                stroke="rgba(255,255,255,0.75)"
                strokeWidth={W * 0.0022}
              />
              <circle cx={ax} cy={ay} r={W * 0.009} fill="none" stroke="#fff" strokeWidth={W * 0.0028} />
            </g>
          );
        })}

        {/* age banner */}
        <text
          x={W / 2}
          y={H + BOT * 0.42}
          fill="#8A93A0"
          fontFamily="IBM Plex Mono, monospace"
          fontSize={W * 0.026}
          letterSpacing={W * 0.006}
          textAnchor="middle"
        >
          APPARENT SKIN AGE
        </text>
        <text
          x={W / 2}
          y={H + BOT * 0.88}
          fill="#FFFFFF"
          fontFamily="Archivo, Helvetica, Arial, sans-serif"
          fontSize={W * 0.11}
          fontWeight="900"
          textAnchor="middle"
        >
          {skin.age || "\u2014"}
        </text>
        <text
          x={vbX + W * 0.05}
          y={H + BOT * 0.88}
          fill="#5C6673"
          fontFamily="IBM Plex Mono, monospace"
          fontSize={W * 0.022}
          textAnchor="start"
        >
          Higher is better on every measure
        </text>
      </svg>

      <div className="chips">
        <button className="chip" onClick={save}>
          {saving === "working" ? "Saving\u2026" : saving === "failed" ? "Save failed" : "Save PNG"}
        </button>
      </div>
    </div>
  );
}

/* ---------------------------- main app ----------------------------- */

export default function SkinReadout() {
  const [image, setImage] = useState(null);
  const [status, setStatus] = useState("idle"); // idle | reading | done | error
  const [result, setResult] = useState(null);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [mode, setMode] = useState("upload"); // upload | camera
  const [cam, setCam] = useState("off"); // off | starting | live | denied | blocked
  const [facing, setFacing] = useState("user");
  const [count, setCount] = useState(0);
  const [steady, setSteady] = useState(false);
  const [pass, setPass] = useState(0);
  const [show, setShow] = useState({ reticle: true, mesh: true, zones: false });
  const [view, setView] = useState("poster");
  const inputRef = useRef(null);
  const videoRef = useRef(null);
  const streamRef = useRef(null);
  const timerRef = useRef(null);

  const loadFile = useCallback(async (file) => {
    if (!file) return;
    setError("");
    setResult(null);
    setStatus("idle");
    try {
      setImage(await prepImage(file));
    } catch (e) {
      setImage(null);
      setStatus("error");
      setError(e.message);
    }
  }, []);

  /* ---------------------------- camera ---------------------------- */

  const stopCamera = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    setCount(0);
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    if (videoRef.current) videoRef.current.srcObject = null;
    setCam("off");
  }, []);

  const startCamera = useCallback(
    async (want) => {
      const side = want || facing;
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        setCam("blocked");
        return;
      }
      if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop());
      setCam("starting");
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: { ideal: side }, width: { ideal: 1280 }, height: { ideal: 1280 } },
          audio: false,
        });
        streamRef.current = stream;
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          try {
            await videoRef.current.play();
          } catch (_) {}
        }
        setFacing(side);
        setCam("live");
      } catch (e) {
        setCam(e && e.name === "NotAllowedError" ? "denied" : "blocked");
      }
    },
    [facing]
  );

  const shoot = useCallback(() => {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return;
    setImage(toPayload(v, v.videoWidth, v.videoHeight));
    setResult(null);
    setStatus("idle");
    setError("");
    stopCamera();
  }, [stopCamera]);

  const shootIn = useCallback(
    (secs) => {
      if (timerRef.current) return;
      let n = secs;
      setCount(n);
      timerRef.current = setInterval(() => {
        n -= 1;
        setCount(n);
        if (n <= 0) {
          clearInterval(timerRef.current);
          timerRef.current = null;
          shoot();
        }
      }, 1000);
    },
    [shoot]
  );

  useEffect(() => stopCamera, [stopCamera]);

  /* --------------------------- analysis --------------------------- */

  const callModel = useCallback(async (b64, prompt) => {
    const res = await fetch("/api/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: "claude-sonnet-4-6",
        max_tokens: 1000,
        messages: [
          {
            role: "user",
            content: [
              { type: "image", source: { type: "base64", media_type: "image/jpeg", data: b64 } },
              { type: "text", text: prompt },
            ],
          },
        ],
      }),
    });
    let data = null;
    try {
      data = await res.json();
    } catch (_) {
      /* Use the status-based error below if the response is not JSON. */
    }
    if (!res.ok) {
      throw new Error(
        data?.error?.message ||
          data?.error ||
          `The analysis service returned HTTP ${res.status}. Try again in a moment.`
      );
    }
    const text = (data.content || [])
      .map((b) => (b.type === "text" ? b.text : ""))
      .filter(Boolean)
      .join("\n");
    const clean = text.replace(/```json/g, "").replace(/```/g, "").trim();
    const a = clean.indexOf("{");
    const b = clean.lastIndexOf("}");
    if (a < 0 || b < 0) throw new Error("The reading came back unreadable. Try again.");
    return JSON.parse(clean.slice(a, b + 1));
  }, []);

  const runOnce = useCallback(async () => {
    /* Pass one: where is the face? */
    let box = null;
    try {
      const found = await callModel(image.base64, BOX_PROMPT);
      const b = found?.box;
      if (found?.found !== false && Array.isArray(b) && b.length === 4 && b[2] > 0.04 && b[3] > 0.04) {
        const pad = 0.16;
        const x = clamp01(b[0] - b[2] * pad);
        const y = clamp01(b[1] - b[3] * pad);
        box = [x, y, clamp01(b[0] + b[2] * (1 + pad)) - x, clamp01(b[1] + b[3] * (1 + pad)) - y];
      }
    } catch (_) {
      /* no box, fall back to reading the whole frame */
    }

    /* Pass two: read the skin on the crop, where the face has far more pixels. */
    let payload = image;
    if (box) {
      try {
        payload = cropTo(await loadImg(image.dataUrl), box);
      } catch (_) {
        box = null;
      }
    }

    const r = await callModel(payload.base64, PROMPT);

    /* Landmarks come back in crop space. Put them back in frame space. */
    if (box && r && r.lm) {
      const mapped = {};
      Object.keys(r.lm).forEach((k) => {
        const p = r.lm[k];
        if (Array.isArray(p) && p.length >= 2) {
          mapped[k] = [box[0] + p[0] * box[2], box[1] + p[1] * box[3]];
        }
      });
      r.lm = mapped;
    }
    if (r) r.box = box;
    return r;
  }, [image, callModel]);

  const analyze = useCallback(async () => {
    if (!image) return;
    setStatus("reading");
    setError("");
    setResult(null);
    const runs = steady ? 3 : 1;
    try {
      const out = [];
      for (let i = 0; i < runs; i++) {
        setPass(i + 1);
        let r;
        try {
          r = await runOnce();
        } catch (e) {
          r = await runOnce(); // one repair attempt, usually a truncated or fenced reply
        }
        out.push(r);
        if (r?.face?.detected === false) break;
      }
      const base = out[0];
      if (out.length > 1 && base.skin) {
        base.skin.score = median(out.map((r) => r?.skin?.score));
        base.skin.metrics = (base.skin.metrics || []).map((m) => {
          const vals = out.map((r) => (r?.skin?.metrics || []).find((x) => x.k === m.k)?.v);
          return { ...m, v: median(vals), band: spread(vals) };
        });
        base.skin.zones = (base.skin.zones || []).map((z) => ({
          ...z,
          v: median(out.map((r) => (r?.skin?.zones || []).find((x) => x.z === z.z)?.v)),
        }));
        base.pose.yaw = median(out.map((r) => r?.pose?.yaw));
        base.pose.pitch = median(out.map((r) => r?.pose?.pitch));
        base.pose.roll = median(out.map((r) => r?.pose?.roll));
        base.runs = out.length;
      }
      setResult(base);
      setStatus("done");
    } catch (e) {
      setStatus("error");
      setError(e.message || "The reading failed. Try again.");
    } finally {
      setPass(0);
    }
  }, [image, steady, runOnce]);

  const reset = () => {
    stopCamera();
    setImage(null);
    setResult(null);
    setStatus("idle");
    setError("");
    if (inputRef.current) inputRef.current.value = "";
  };

  const skin = result?.skin;
  const pose = result?.pose;
  const capture = result?.capture;
  const noFace = result && result.face && result.face.detected === false;

  const metrics = skin?.metrics?.length
    ? [...skin.metrics].sort((a, b) => METRIC_ORDER.indexOf(a.k) - METRIC_ORDER.indexOf(b.k))
    : [];

  const zoneScores = {};
  (skin?.zones || []).forEach((z) => {
    zoneScores[z.z] = z.v;
  });

  const meshOk = status === "done" && meshIsSane(result?.lm);

  /* Confidence follows capture quality, knocked down for an awkward angle. */
  let conf = null;
  if (capture) {
    const q = Math.round(
      ((capture.lighting || 0) + (capture.sharpness || 0) + (capture.framing || 0)) / 3
    );
    const adj = pose && pose.usable === false ? q - 20 : q;
    conf = {
      v: Math.max(0, adj),
      label: adj >= 75 ? "High" : adj >= 50 ? "Moderate" : "Low",
      why:
        adj >= 75
          ? "Sharp, evenly lit and well framed."
          : capture.flag || "Capture quality limits how much the surface numbers are worth.",
    };
  }

  return (
    <div className="sr-root">
      <style>{`
@import url('https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,400..900&family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap');

.sr-root {
  --paper: #E9EBEE; --panel: #FFFFFF; --ink: #101318; --slate: #626B77;
  --line: #C9CFD6; --uv: #3D1E82; --uv-bright: #7C4DFF; --good: #10796B; --watch: #A9541F;
  background: var(--paper); color: var(--ink);
  font-family: "IBM Plex Sans", system-ui, sans-serif;
  min-height: 100%; padding: 28px 20px 56px; -webkit-font-smoothing: antialiased;
}
.sr-root * { box-sizing: border-box; }
.sr-wrap { max-width: 1080px; margin: 0 auto; }

.sr-eyebrow { font-family: "IBM Plex Mono", monospace; font-size: 11px; letter-spacing: .18em;
  text-transform: uppercase; color: var(--uv); margin: 0 0 14px; }
.sr-title { font-family: "Archivo", sans-serif; font-variation-settings: "wdth" 118, "wght" 800;
  font-size: clamp(34px, 7vw, 62px); line-height: .94; letter-spacing: -.02em;
  margin: 0 0 12px; text-transform: uppercase; }
.sr-lede { max-width: 48ch; margin: 0 0 30px; color: var(--slate); font-size: 15px; line-height: 1.55; }

.sr-grid { display: grid; grid-template-columns: minmax(0, 5fr) minmax(0, 7fr); gap: 22px; align-items: start; }
@media (max-width: 860px) { .sr-grid { grid-template-columns: 1fr; } }

.panel { background: var(--panel); border: 1px solid var(--line); }
.panel-head { display: flex; justify-content: space-between; align-items: center;
  padding: 11px 14px; border-bottom: 1px solid var(--line);
  font-family: "IBM Plex Mono", monospace; font-size: 10.5px;
  letter-spacing: .16em; text-transform: uppercase; color: var(--slate); }
.panel-body { padding: 16px; }

/* ---- glossary term ---- */
.term-wrap { position: relative; display: inline-block; }
.term { font: inherit; color: inherit; background: none; border: 0; padding: 0; cursor: help;
  border-bottom: 1px dotted var(--uv-bright); text-underline-offset: 2px; }
.term:hover, .term:focus-visible { color: var(--uv); }
.term:focus-visible { outline: 2px solid var(--uv-bright); outline-offset: 2px; }
.tip { position: absolute; bottom: calc(100% + 8px); left: 0; z-index: 40; width: 250px;
  background: var(--ink); color: #EDEEF1; font-size: 12px; font-weight: 400; line-height: 1.5;
  padding: 10px 12px; text-align: left; box-shadow: 0 6px 22px rgba(16,19,24,.24); }
.tip-k { display: block; font-family: "IBM Plex Mono", monospace; font-size: 9.5px;
  letter-spacing: .14em; text-transform: uppercase; color: #B79CFF; margin-bottom: 5px; }
.tip::after { content: ""; position: absolute; top: 100%; left: 14px;
  border: 6px solid transparent; border-top-color: var(--ink); }

/* ---- source toggle ---- */
.seg { display: flex; border: 1px solid var(--line); margin-bottom: 14px; }
.seg-btn { flex: 1; padding: 9px 10px; background: transparent; border: 0; cursor: pointer;
  font-family: "IBM Plex Mono", monospace; font-size: 10.5px; letter-spacing: .14em;
  text-transform: uppercase; color: var(--slate); }
.seg-btn + .seg-btn { border-left: 1px solid var(--line); }
.seg-btn.is-on { background: var(--uv); color: #fff; }
.seg-btn:focus-visible { outline: 2px solid var(--uv-bright); outline-offset: -2px; }

/* ---- capture ---- */
.drop { position: relative; aspect-ratio: 3 / 4; width: 100%; background: #F4F5F7;
  border: 1px dashed var(--line); display: flex; flex-direction: column; align-items: center;
  justify-content: center; text-align: center; padding: 24px; cursor: pointer; overflow: hidden;
  transition: border-color .15s, background .15s; }
.drop:hover, .drop.is-drag { border-color: var(--uv-bright); background: #F1EEFB; }
.drop:focus-visible { outline: 2px solid var(--uv-bright); outline-offset: 3px; }
.drop-icon { width: 42px; height: 42px; border: 1.5px solid var(--uv); border-radius: 50%;
  display: grid; place-items: center; margin-bottom: 14px; color: var(--uv);
  font-family: "IBM Plex Mono", monospace; font-size: 15px; }
.drop-main { font-weight: 600; font-size: 14.5px; margin: 0 0 5px; }
.drop-sub { color: var(--slate); font-size: 12.5px; margin: 0; line-height: 1.5; }

.poster { width: 100%; background: #0D0F13; }
.poster svg { display: block; }
.shot { position: relative; width: 100%; background: #101318; overflow: hidden; }
.shot img { width: 100%; height: 100%; object-fit: contain; display: block; }
.mesh { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }

.reticle { position: absolute; inset: 9%; pointer-events: none; }
.r-corner { position: absolute; width: 20px; height: 20px; border: 1.5px solid var(--uv-bright); }
.r-corner.tl { top: 0; left: 0; border-right: 0; border-bottom: 0; }
.r-corner.tr { top: 0; right: 0; border-left: 0; border-bottom: 0; }
.r-corner.bl { bottom: 0; left: 0; border-right: 0; border-top: 0; }
.r-corner.br { bottom: 0; right: 0; border-left: 0; border-top: 0; }
.r-v { position: absolute; top: 0; bottom: 0; width: 1px; background: rgba(124,77,255,.75); }
.r-h { position: absolute; left: 0; right: 0; height: 1px; background: rgba(124,77,255,.75); }

.scan { position: absolute; left: 0; right: 0; height: 90px; pointer-events: none;
  background: linear-gradient(180deg, rgba(124,77,255,0) 0%, rgba(124,77,255,.55) 50%, rgba(124,77,255,0) 100%);
  animation: sweep 1.5s ease-in-out infinite; }
@keyframes sweep { 0% { top: -90px; } 100% { top: 100%; } }

.chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.chip { font-family: "IBM Plex Mono", monospace; font-size: 10px; letter-spacing: .12em;
  text-transform: uppercase; padding: 7px 10px; border: 1px solid var(--line);
  background: transparent; color: var(--slate); cursor: pointer; }
.chip.is-on { background: #F1EEFB; border-color: var(--uv-bright); color: var(--uv); }
.chip:focus-visible { outline: 2px solid var(--uv-bright); outline-offset: 2px; }

/* ---- live camera ---- */
.cam { position: relative; width: 100%; aspect-ratio: 3 / 4; background: #101318; overflow: hidden; }
.cam video { width: 100%; height: 100%; object-fit: cover; display: block; }
.cam video.mirror { transform: scaleX(-1); }
.cam-guide { position: absolute; inset: 0; pointer-events: none; }
.cam-oval { position: absolute; left: 50%; top: 46%; transform: translate(-50%, -50%);
  width: 62%; height: 74%; border: 1.5px dashed rgba(124,77,255,.85); border-radius: 50% / 42%; }
.cam-eyeline { position: absolute; left: 16%; right: 16%; top: 38%; height: 1px; background: rgba(124,77,255,.6); }
.cam-eyeline::after { content: "eye line"; position: absolute; right: 0; top: 5px;
  font-family: "IBM Plex Mono", monospace; font-size: 9px; letter-spacing: .14em;
  text-transform: uppercase; color: rgba(255,255,255,.75); }
.cam-state { position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; text-align: center; padding: 26px;
  color: #E9EBEE; font-size: 13px; line-height: 1.6; }
.cam-state strong { display: block; font-size: 14.5px; margin-bottom: 6px; color: #fff; }
.cam-count { position: absolute; inset: 0; display: grid; place-items: center;
  font-family: "Archivo", sans-serif; font-variation-settings: "wdth" 125, "wght" 900;
  font-size: 110px; color: #fff; text-shadow: 0 2px 24px rgba(0,0,0,.55); }
.cam-bar { display: flex; gap: 7px; margin-top: 10px; }
.cam-bar .btn { font-size: 12.5px; padding: 10px 8px; }

.btn-row { display: flex; gap: 9px; margin-top: 14px; }
.btn { flex: 1; font-family: "IBM Plex Sans", sans-serif; font-size: 13.5px; font-weight: 600;
  padding: 12px 14px; border: 1px solid var(--uv); background: var(--uv); color: #fff;
  cursor: pointer; letter-spacing: .01em; transition: background .15s; }
.btn:hover { background: #2E1566; }
.btn:disabled { opacity: .45; cursor: default; }
.btn.ghost { background: transparent; color: var(--ink); border-color: var(--line); flex: 0 0 auto; }
.btn.ghost:hover { border-color: var(--ink); background: transparent; }
.btn:focus-visible { outline: 2px solid var(--uv-bright); outline-offset: 2px; }

.opt { display: flex; align-items: flex-start; gap: 9px; margin-top: 13px; font-size: 12.5px;
  color: var(--slate); line-height: 1.5; cursor: pointer; }
.opt input { margin-top: 2px; accent-color: var(--uv); }
.opt b { color: var(--ink); font-weight: 600; }

.hint { margin: 12px 0 0; font-size: 12px; line-height: 1.55; color: var(--slate); }

/* ---- readout ---- */
.empty { padding: 46px 20px; text-align: center; color: var(--slate); font-size: 13.5px; line-height: 1.6; }
.empty strong { display: block; color: var(--ink); font-size: 14.5px; margin-bottom: 6px; }

.score-block { display: flex; align-items: flex-end; gap: 18px; padding-bottom: 16px; border-bottom: 1px solid var(--line); }
.score-num { font-family: "Archivo", sans-serif; font-variation-settings: "wdth" 125, "wght" 900;
  font-size: 76px; line-height: .8; letter-spacing: -.03em; }
.score-side { padding-bottom: 6px; }
.score-cap { font-family: "IBM Plex Mono", monospace; font-size: 10.5px; letter-spacing: .16em;
  text-transform: uppercase; color: var(--slate); }
.score-age { font-weight: 400; color: var(--slate); }
.score-type { font-size: 14px; font-weight: 600; margin-top: 3px; text-transform: capitalize; }

.strip { display: flex; height: 7px; margin-top: 14px; }
.strip span { flex: 1; }

.conf { display: flex; gap: 10px; align-items: baseline; margin-top: 14px; padding: 10px 12px;
  background: #F7F8F9; border-left: 2px solid var(--uv); font-size: 12.5px; line-height: 1.5; color: var(--slate); }
.conf b { font-size: 13px; color: var(--ink); white-space: nowrap; }

.sec-label { font-family: "IBM Plex Mono", monospace; font-size: 10.5px; letter-spacing: .16em;
  text-transform: uppercase; color: var(--slate); margin: 22px 0 12px; }

.axis { display: grid; grid-template-columns: 52px 1fr 44px; align-items: center; gap: 10px; margin-bottom: 9px; }
.axis-label { font-family: "IBM Plex Mono", monospace; font-size: 11px; color: var(--slate); text-transform: uppercase; }
.axis-track { position: relative; height: 20px; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line);
  background: repeating-linear-gradient(90deg, var(--line) 0 1px, transparent 1px 10%); }
.axis-zero { position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: var(--slate); }
.axis-dot { position: absolute; top: 50%; width: 9px; height: 9px; background: var(--uv-bright);
  transform: translate(-50%, -50%); border-radius: 50%; transition: left .5s cubic-bezier(.2,.8,.3,1); }
.axis-val { font-family: "IBM Plex Mono", monospace; font-size: 11.5px; text-align: right; }

.pose-label { font-size: 15px; font-weight: 600; margin: 0 0 3px; }
.pose-fix { font-size: 13px; color: var(--watch); margin: 0 0 14px; line-height: 1.5; }

.meter { margin-bottom: 15px; animation: rise .45s ease both; }
@keyframes rise { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.meter-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 5px; }
.meter-name { font-size: 13.5px; font-weight: 600; }
.meter-val { font-family: "IBM Plex Mono", monospace; font-size: 13px; }
.meter-band { font-style: normal; color: var(--slate); font-size: 11px; margin-left: 4px; }
.meter-track { position: relative; height: 12px; background: #F0F1F4;
  background-image: repeating-linear-gradient(90deg, var(--line) 0 1px, transparent 1px 10%); }
.meter-fill { position: absolute; left: 0; top: 0; bottom: 0; background: var(--uv); opacity: .16; }
.meter-spread { position: absolute; top: 0; bottom: 0; background: rgba(124,77,255,.3); }
.meter-needle { position: absolute; top: -2px; bottom: -2px; width: 2px; background: var(--uv); transform: translateX(-1px); }
.meter-note { margin: 5px 0 0; font-size: 12.5px; color: var(--slate); line-height: 1.5; }

.zones { border-top: 1px solid var(--line); }
.zone { display: grid; grid-template-columns: 104px 34px 1fr; gap: 10px; padding: 10px 0;
  border-bottom: 1px solid var(--line); align-items: baseline; }
.zone-name { font-family: "IBM Plex Mono", monospace; font-size: 11px; text-transform: uppercase;
  color: var(--uv); letter-spacing: .06em; }
.zone-val { font-family: "IBM Plex Mono", monospace; font-size: 12px; }
.zone-note { font-size: 13px; line-height: 1.5; }

.tags { display: flex; flex-wrap: wrap; gap: 7px; }
.tag { font-size: 12.5px; padding: 6px 10px; border: 1px solid var(--line); background: #F7F8F9; }
.tag.warn { border-color: #E3C6AE; background: #FBF3EC; color: var(--watch); }

.steps { margin: 0; padding: 0; list-style: none; counter-reset: s; }
.steps li { display: grid; grid-template-columns: 26px 1fr; gap: 8px; font-size: 13.5px;
  line-height: 1.5; padding: 8px 0; border-bottom: 1px solid var(--line); }
.steps li::before { counter-increment: s; content: counter(s, decimal-leading-zero);
  font-family: "IBM Plex Mono", monospace; font-size: 11px; color: var(--uv); padding-top: 2px; }

.alert { border: 1px solid #E3C6AE; background: #FBF3EC; color: var(--watch); padding: 12px 14px;
  font-size: 13px; line-height: 1.55; margin-bottom: 16px; }
.alert strong { display: block; margin-bottom: 3px; color: var(--ink); }

.about { max-width: 1080px; margin: 22px auto 0; background: var(--panel); border: 1px solid var(--line); }
.about summary { padding: 13px 16px; cursor: pointer; font-family: "IBM Plex Mono", monospace;
  font-size: 10.5px; letter-spacing: .16em; text-transform: uppercase; color: var(--uv); }
.about summary:focus-visible { outline: 2px solid var(--uv-bright); outline-offset: -2px; }
.about-body { padding: 0 16px 18px; font-size: 13px; line-height: 1.65; color: var(--slate); }
.about-body h4 { font-size: 13px; color: var(--ink); margin: 14px 0 5px; }
.about-body ul { margin: 0; padding-left: 18px; }
.about-body li { margin-bottom: 5px; }

.foot { max-width: 1080px; margin: 22px auto 0; font-size: 12px; color: var(--slate);
  line-height: 1.6; border-top: 1px solid var(--line); padding-top: 14px; }

@media (prefers-reduced-motion: reduce) {
  .scan { animation: none; opacity: .35; top: 45%; }
  .meter { animation: none; }
  .axis-dot { transition: none; }
}
      `}</style>

      <div className="sr-wrap">
        <p className="sr-eyebrow">Skin readout &middot; single frame</p>
        <h1 className="sr-title">Read your skin<br />from one photo</h1>
        <p className="sr-lede">
          Take a straight-on photo in even light. The app maps your face, checks how your head is
          angled, then reports what it can see across six surface measures and five zones. Any term
          with a dotted underline will explain itself.
        </p>

        <div className="sr-grid">
          {/* -------- capture -------- */}
          <div className="panel">
            <div className="panel-head">
              <span>01 &nbsp;Capture</span>
              <span>{image ? "Frame loaded" : cam === "live" ? "Camera live" : "Empty"}</span>
            </div>
            <div className="panel-body">
              {!image ? (
                <div className="seg" role="group" aria-label="Photo source">
                  <button
                    className={mode === "upload" ? "seg-btn is-on" : "seg-btn"}
                    onClick={() => {
                      stopCamera();
                      setMode("upload");
                    }}
                  >
                    Upload a file
                  </button>
                  <button
                    className={mode === "camera" ? "seg-btn is-on" : "seg-btn"}
                    onClick={() => {
                      setMode("camera");
                      if (cam === "off") startCamera(facing);
                    }}
                  >
                    Use camera
                  </button>
                </div>
              ) : null}

              {!image && mode === "camera" ? (
                <>
                  <div className="cam">
                    <video ref={videoRef} className={facing === "user" ? "mirror" : ""} playsInline muted autoPlay />
                    {cam === "live" ? (
                      <div className="cam-guide">
                        <div className="cam-oval" />
                        <div className="cam-eyeline" />
                      </div>
                    ) : null}
                    {count > 0 ? <div className="cam-count">{count}</div> : null}
                    {cam === "starting" ? <div className="cam-state">Starting the camera&hellip;</div> : null}
                    {cam === "denied" ? (
                      <div className="cam-state">
                        <strong>Camera access is turned off</strong>
                        Allow the camera for this page in your browser settings, then press Start
                        camera. Or switch to Upload a file.
                      </div>
                    ) : null}
                    {cam === "blocked" ? (
                      <div className="cam-state">
                        <strong>No camera available here</strong>
                        This browser or frame will not hand over a camera. Use Upload a file, which
                        opens the camera app on a phone.
                      </div>
                    ) : null}
                    {cam === "off" ? (
                      <div className="cam-state">
                        <strong>Camera is off</strong>
                        Press Start camera to line up your shot.
                      </div>
                    ) : null}
                  </div>

                  <div className="cam-bar">
                    {cam === "live" ? (
                      <>
                        <button className="btn" onClick={shoot} disabled={count > 0}>Take photo</button>
                        <button className="btn ghost" onClick={() => shootIn(3)} disabled={count > 0}>3s</button>
                        <button
                          className="btn ghost"
                          onClick={() => startCamera(facing === "user" ? "environment" : "user")}
                          disabled={count > 0}
                        >
                          Flip
                        </button>
                        <button className="btn ghost" onClick={stopCamera} disabled={count > 0}>Stop</button>
                      </>
                    ) : (
                      <button className="btn" onClick={() => startCamera(facing)} disabled={cam === "starting"}>
                        {cam === "starting" ? "Starting\u2026" : "Start camera"}
                      </button>
                    )}
                  </div>

                  <p className="hint">
                    Fill the oval with your face and put your eyes on the line. The preview is
                    mirrored so it feels like a mirror, but the photo is saved the right way round.
                  </p>
                </>
              ) : null}

              {!image && mode === "upload" ? (
                <div
                  className={`drop${dragging ? " is-drag" : ""}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => inputRef.current?.click()}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      inputRef.current?.click();
                    }
                  }}
                  onDragOver={(e) => {
                    e.preventDefault();
                    setDragging(true);
                  }}
                  onDragLeave={() => setDragging(false)}
                  onDrop={(e) => {
                    e.preventDefault();
                    setDragging(false);
                    loadFile(e.dataTransfer.files?.[0]);
                  }}
                >
                  <div className="drop-icon">+</div>
                  <p className="drop-main">Add a photo of your face</p>
                  <p className="drop-sub">
                    Drop a file here, or tap to choose one.
                    <br />
                    On a phone this opens the camera.
                  </p>
                </div>
              ) : null}

              {image ? (
                <>
                  {status === "done" && skin && view === "poster" ? (
                    <Poster image={image} result={result} meshOk={meshOk} />
                  ) : (
                    <div className="shot" style={{ aspectRatio: `${image.w} / ${image.h}` }}>
                      <img src={image.dataUrl} alt="The photo being analyzed" />
                      {status === "done" && show.reticle && pose ? <Reticle pose={pose} /> : null}
                      {status === "done" && show.mesh && meshOk ? (
                        <Mesh lm={result.lm} zoneScores={zoneScores} shaded={show.zones} />
                      ) : null}
                      {status === "reading" ? <div className="scan" /> : null}
                    </div>
                  )}

                  {status === "done" && !meshOk && !noFace ? (
                    <p className="hint">
                      Face map skipped. The points came back out of shape, so the app dropped them
                      rather than draw a mesh in the wrong place. Callouts fall back to the detected
                      face box, and the skin readout below does not depend on either.
                    </p>
                  ) : null}

                  {status === "done" && skin ? (
                    <div className="chips">
                      <button
                        className={view === "poster" ? "chip is-on" : "chip"}
                        aria-pressed={view === "poster"}
                        onClick={() => setView("poster")}
                      >
                        Annotated
                      </button>
                      <button
                        className={view === "plain" ? "chip is-on" : "chip"}
                        aria-pressed={view === "plain"}
                        onClick={() => setView("plain")}
                      >
                        Plain
                      </button>
                    </div>
                  ) : null}

                  {status === "done" && meshOk && view === "plain" ? (
                    <div className="chips">
                      <button
                        className={show.mesh ? "chip is-on" : "chip"}
                        aria-pressed={show.mesh}
                        onClick={() => setShow((s) => ({ ...s, mesh: !s.mesh }))}
                      >
                        Mesh
                      </button>
                      <button
                        className={show.zones ? "chip is-on" : "chip"}
                        aria-pressed={show.zones}
                        onClick={() => setShow((s) => ({ ...s, zones: !s.zones, mesh: true }))}
                      >
                        Zone shading
                      </button>
                      <button
                        className={show.reticle ? "chip is-on" : "chip"}
                        aria-pressed={show.reticle}
                        onClick={() => setShow((s) => ({ ...s, reticle: !s.reticle }))}
                      >
                        Reticle
                      </button>
                    </div>
                  ) : null}
                </>
              ) : null}

              <input
                ref={inputRef}
                type="file"
                accept="image/*"
                capture="user"
                style={{ display: "none" }}
                onChange={(e) => loadFile(e.target.files?.[0])}
              />

              {image || mode === "upload" ? (
                <div className="btn-row">
                  <button
                    className="btn"
                    onClick={image ? analyze : () => inputRef.current?.click()}
                    disabled={status === "reading"}
                  >
                    {status === "reading"
                      ? steady
                        ? `Reading ${pass} of 3\u2026`
                        : "Reading\u2026"
                      : image
                      ? status === "done"
                        ? "Read again"
                        : "Read this photo"
                      : "Choose a photo"}
                  </button>
                  {image ? (
                    <button className="btn ghost" onClick={reset} disabled={status === "reading"}>
                      {mode === "camera" ? "Retake" : "Clear"}
                    </button>
                  ) : null}
                </div>
              ) : null}

              {image ? (
                <label className="opt">
                  <input
                    type="checkbox"
                    checked={steady}
                    onChange={(e) => setSteady(e.target.checked)}
                    disabled={status === "reading"}
                  />
                  <span>
                    <b>Steady mode</b> &mdash; read the same photo three times and show the middle
                    value with its <Term>Spread</Term>. Slower, but it shows you how much the numbers
                    wobble.
                  </span>
                </label>
              ) : null}

              <p className="hint">
                Best results: face the camera straight on, no glasses or hat, soft daylight from the
                front, no makeup or filters. Photos are sent for analysis and are not saved.
              </p>
            </div>
          </div>

          {/* -------- readout -------- */}
          <div className="panel">
            <div className="panel-head">
              <span>02 &nbsp;Readout</span>
              <span>{status === "reading" ? "Working" : status === "done" ? "Complete" : "Standby"}</span>
            </div>
            <div className="panel-body">
              {status === "error" ? (
                <div className="alert">
                  <strong>The reading stopped</strong>
                  {error}
                </div>
              ) : null}

              {status !== "done" && status !== "error" ? (
                <div className="empty">
                  <strong>{status === "reading" ? "Reading the frame" : "Nothing to read yet"}</strong>
                  {status === "reading"
                    ? "Mapping the face, then checking angle, light and skin surface."
                    : "Take a photo or upload one, then press Read this photo."}
                </div>
              ) : null}

              {noFace ? (
                <div className="alert">
                  <strong>No face found in this photo</strong>
                  Upload a photo where one face fills most of the frame, taken straight on.
                </div>
              ) : null}

              {status === "done" && skin ? (
                <>
                  {capture?.flag ? (
                    <div className="alert">
                      <strong>Capture note</strong>
                      {capture.flag}
                    </div>
                  ) : null}

                  <div className="score-block">
                    <div className="score-num">{skin.score}</div>
                    <div className="score-side">
                      <div className="score-cap">
                        <Term>Surface score</Term>
                      </div>
                      <div className="score-type">
                        <Term k="Skin type">{skin.type} skin</Term>
                        {skin.age ? (
                          <span className="score-age">
                            &middot; <Term k="Apparent skin age">looks about {skin.age}</Term>
                          </span>
                        ) : null}
                      </div>
                    </div>
                  </div>
                  <div className="strip">
                    {metrics.map((m) => (
                      <span
                        key={m.k}
                        title={`${m.k} ${m.v}`}
                        style={{
                          background: `color-mix(in srgb, var(--uv) ${Math.max(10, Math.min(100, m.v))}%, #E4E6EA)`,
                        }}
                      />
                    ))}
                  </div>

                  {conf ? (
                    <div className="conf">
                      <b>
                        <Term>Confidence</Term>: {conf.label}
                      </b>
                      <span>
                        {conf.why}
                        {result.runs ? ` Averaged over ${result.runs} readings.` : ""}
                      </span>
                    </div>
                  ) : null}

                  <p className="sec-label">Head posture</p>
                  <p className="pose-label">{pose?.label}</p>
                  {pose?.fix ? <p className="pose-fix">{pose.fix}</p> : null}
                  <Axis label="Yaw" value={pose?.yaw} range={60} />
                  <Axis label="Pitch" value={pose?.pitch} range={45} />
                  <Axis label="Roll" value={pose?.roll} range={30} />

                  <p className="sec-label">Surface measures</p>
                  {metrics.map((m, i) => (
                    <Meter key={m.k} name={m.k} value={m.v} note={m.note} band={m.band} delay={i * 60} />
                  ))}

                  <p className="sec-label">By zone</p>
                  <div className="zones">
                    {(skin.zones || []).map((z) => (
                      <div className="zone" key={z.z}>
                        <span className="zone-name">
                          <Term>{z.z}</Term>
                        </span>
                        <span className="zone-val">{z.v}</span>
                        <span className="zone-note">{z.note}</span>
                      </div>
                    ))}
                  </div>

                  {skin.watch?.length ? (
                    <>
                      <p className="sec-label">Worth a second look</p>
                      <div className="tags">
                        {skin.watch.map((w, i) => (
                          <span className="tag warn" key={i}>{w}</span>
                        ))}
                      </div>
                    </>
                  ) : null}

                  {skin.next?.length ? (
                    <>
                      <p className="sec-label">What to do next</p>
                      <ul className="steps">
                        {skin.next.map((n, i) => (
                          <li key={i}>{n}</li>
                        ))}
                      </ul>
                    </>
                  ) : null}
                </>
              ) : null}
            </div>
          </div>
        </div>
      </div>

      <details className="about">
        <summary>How accurate is this, really?</summary>
        <div className="about-body">
          <p>
            These numbers are estimates from one 2D photo, made by a general-purpose vision model.
            Nothing here is measured against a calibrated instrument, so treat a score as an
            informed description rather than a reading off a meter.
          </p>
          <h4>What moves the numbers even when your skin has not changed</h4>
          <ul>
            <li>Light. Warm indoor light reads as redness. A window behind you flattens texture.</li>
            <li>Your phone. Most cameras smooth skin and lift shadows by default, which quietly inflates texture and pore scores.</li>
            <li>Time of day. Shine climbs through the day. Morning and evening are different photos of the same skin.</li>
            <li>Angle and distance. A closer or more tilted shot changes what the model can resolve.</li>
            <li>The model itself. Ask twice, get two slightly different answers. Steady mode exists so you can watch that happen instead of taking my word for it.</li>
          </ul>
          <h4>What it is reasonably good at</h4>
          <ul>
            <li>Describing what is visible: where shine sits, where tone is uneven, whether under-eyes look dark.</li>
            <li>Relative change over time, if you keep the light, distance and time of day fixed.</li>
            <li>Ranking your own zones against each other within a single photo.</li>
          </ul>
          <h4>What it is not good at</h4>
          <ul>
            <li>Absolute numbers. A 71 does not mean the same thing as anyone else's 71.</li>
            <li>Anything under the surface. Hydration and oil are physical quantities that need contact instruments to measure properly.</li>
            <li>Fine differences. A four-point move between two photos is noise, not progress.</li>
          </ul>
          <h4>How to get more out of it</h4>
          <ul>
            <li>Same spot, same light, same time of day, every time. Consistency beats resolution.</li>
            <li>Turn off beauty filters and HDR if your camera lets you.</li>
            <li>Use Steady mode and trust wide-spread scores less.</li>
            <li>Compare weeks apart, not days apart.</li>
          </ul>
        </div>
      </details>

      <p className="foot">
        This app describes how skin looks in a photo. It is not a medical device and does not
        diagnose anything. The face mesh is an approximation drawn from points the model marks, not
        a precise face tracker. Anything that itches, bleeds, changes shape or will not heal belongs
        in front of a dermatologist, not a camera.
      </p>
    </div>
  );
}
