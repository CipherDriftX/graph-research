import type { DiscoveryMethod } from './api';

/* --------------------------------------------------------------------------
 * Discovery track.
 *
 * The one encoding the product is actually about: "graph_walk" means the
 * keyword track never returned this channel. Shape backs up colour — filled
 * for graph-walk-only, hollow for keyword-findable — so the distinction holds
 * without colour.
 * ----------------------------------------------------------------------- */

export const TRACK_META: Record<
  DiscoveryMethod,
  { label: string; color: string; filled: boolean; note: string }
> = {
  graph_walk: {
    label: 'Graph walk only',
    color: 'var(--track-graph)',
    filled: true,
    note: 'Keyword search never returned this channel.',
  },
  both: {
    label: 'Both tracks',
    color: 'var(--track-seed)',
    filled: true,
    note: 'Found by keyword search and by the graph walk.',
  },
  keyword: {
    label: 'Keyword',
    color: 'var(--track-keyword)',
    filled: false,
    note: 'Reachable by plain keyword search.',
  },
  unattributed: {
    label: 'Unattributed',
    color: 'var(--ink-3)',
    filled: false,
    note: 'Discovered before per-track attribution existed (checkpoint schema < 4).',
  },
  unhydrated: {
    label: 'Not hydrated',
    color: 'var(--ink-3)',
    filled: false,
    note: 'Seen as a graph edge but never fetched from the YouTube API.',
  },
};
