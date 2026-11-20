// What each pigment means on this page. The colour values live in one place only:
// the --ultramarine, --yellow-ochre, --vermilion and --lamp-black properties in
// src/styles/site.css. Diagrams refer to a kind of file (--portrait, --landscape,
// --stroke, --brush), never to a raw colour, so a colour means the same thing everywhere.

export type Kind = 'portrait' | 'landscape' | 'stroke' | 'brush';

export const pigments: Record<Kind, { name: string; plural: string; fill: string }> = {
  portrait: { name: 'ultramarine', plural: 'the portrait', fill: 'var(--portrait)' },
  landscape: { name: 'yellow ochre', plural: 'the landscapes', fill: 'var(--landscape)' },
  stroke: { name: 'vermilion', plural: 'the strokes', fill: 'var(--stroke)' },
  brush: { name: 'lamp black', plural: 'the brushes', fill: 'var(--brush)' },
};

export const kinds: Kind[] = ['portrait', 'landscape', 'stroke', 'brush'];
