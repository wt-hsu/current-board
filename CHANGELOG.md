# Changelog

All notable changes to the public board are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/): while the board is in beta the
major version stays at 0. A minor bump means something a reader can see
changed (a new panel, a new field in the data model); a patch bump is a fix.

## [Unreleased]

## [0.3.0] - 2026-10-26

### Added
- Guided tour ("How to read this board"): six steps that highlight each panel in turn.
- Phone layout: circuits become a list, tables drop secondary columns, the hero word sits on its own line.
- Glossary tooltips on dotted terms (nameplate, IT load, PPA, grid region, Impact).
- Location precision on the map: dashed outline when an article only named a region or country, with a placed / approximate / unlocated counter.
- Value source grading on deals: stated by the parties, reported, or estimated.

### Changed
- Display typeface is now IBM Plex Sans (body Inter, numbers JetBrains Mono).
- Map crops Antarctica and fits the land mass, so the hero row is ~40% shorter; the legend floats over the map.
- Activity and Deals stack vertically below 1200px.
- Hero headline word now cross-fades instead of rolling, removing the clipped glow.
- Weekly report removed from the public board; the board itself is the deliverable.

### Fixed
- Market-wide totals (e.g. "474 GW of grid requests") no longer count as projects in any MW figure.
- Place names and news outlets no longer appear as parties in Circuits; mirrored relations are deduplicated.
- Generation (nameplate) and data-center demand (IT load) are never summed.

## [0.2.0] - 2026-10-25

### Added
- Interface spec v3.3: three time windows (this week / 8 weeks / 90 days), coarse-to-fine reading order.
- "What am I looking at?" explainer for first-time readers.
- Map zoom and full-screen mode; by-grid-region summary line.
- Side drawer: clicking a cell, company or card opens a filtered slice of the feed.

### Changed
- Visual system: deep navy background, violet-to-cyan gradient accents, lower-chroma cyan for readability.
- Biggest deals: parties written as verbs ("buys power from"), size and value in separate columns with fixed units.

## [0.1.0] - 2026-10-24

### Added
- First public release on GitHub Pages: numbers, activity by layer, biggest deals, committed-capacity map, circuits, signal feed, the panel.
- Weekly pipeline: collect → extract → dashboard, static single-file output.
- Backfill from 2026-08-15.

[Unreleased]: https://github.com/wt-hsu/current-board/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/wt-hsu/current-board/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/wt-hsu/current-board/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/wt-hsu/current-board/releases/tag/v0.1.0
