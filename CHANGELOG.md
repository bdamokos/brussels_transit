<!-- START doctoc generated TOC please keep comment here to allow auto update -->
<!-- DON'T EDIT THIS SECTION, INSTEAD RE-RUN doctoc TO UPDATE -->
**Table of Contents**  *generated with [DocToc](https://github.com/thlorenz/doctoc)*

- [Changelog](#changelog)
  - [v0.2.1 (2025-01-09)](#v021-2025-01-09)
  - [v0.2.0 (2025-01-03)](#v020-2025-01-03)
  - [v0.1.2 (2024-12-30)](#v012-2024-12-30)
  - [v0.1.1 (2024-12-26)](#v011-2024-12-26)
  - [v0.1.0 (2024-12-26)](#v010-2024-12-26)

<!-- END doctoc generated TOC please keep comment here to allow auto update -->

# Changelog

## [v0.2.1](https://github.com/bdamokos/brussels_transit/tree/v0.2.1) (2025-01-09)

[Full Changelog](https://github.com/bdamokos/brussels_transit/compare/v0.2.0...v0.2.1)

**Implemented enhancements:**

- 🚀 Optimize GTFS data processing with C-based precache tool [\#53](https://github.com/bdamokos/brussels_transit/pull/53) ([bdamokos](https://github.com/bdamokos))

**Merged pull requests:**

- Bump pytest from 8.3.3 to 8.3.4 [\#52](https://github.com/bdamokos/brussels_transit/pull/52) ([dependabot[bot]](https://github.com/apps/dependabot))
- Bump niquests from 3.12.0 to 3.12.1 [\#51](https://github.com/bdamokos/brussels_transit/pull/51) ([dependabot[bot]](https://github.com/apps/dependabot))
- Bump numpy from 2.1.3 to 2.2.1 [\#50](https://github.com/bdamokos/brussels_transit/pull/50) ([dependabot[bot]](https://github.com/apps/dependabot))
- Bump uvicorn from 0.32.1 to 0.34.0 [\#49](https://github.com/bdamokos/brussels_transit/pull/49) ([dependabot[bot]](https://github.com/apps/dependabot))
- Bump httpx from 0.27.2 to 0.28.1 [\#47](https://github.com/bdamokos/brussels_transit/pull/47) ([dependabot[bot]](https://github.com/apps/dependabot))
- Bump deepdiff from 8.0.1 to 8.1.1 [\#46](https://github.com/bdamokos/brussels_transit/pull/46) ([dependabot[bot]](https://github.com/apps/dependabot))
- Bump anyio from 4.6.2.post1 to 4.7.0 [\#45](https://github.com/bdamokos/brussels_transit/pull/45) ([dependabot[bot]](https://github.com/apps/dependabot))
- Bump python-dateutil from 2.8.2 to 2.9.0.post0 [\#44](https://github.com/bdamokos/brussels_transit/pull/44) ([dependabot[bot]](https://github.com/apps/dependabot))
- Bump orderly-set from 5.2.2 to 5.2.3 [\#43](https://github.com/bdamokos/brussels_transit/pull/43) ([dependabot[bot]](https://github.com/apps/dependabot))

## [v0.2.0](https://github.com/bdamokos/brussels_transit/tree/v0.2.0) (2025-01-03)

[Full Changelog](https://github.com/bdamokos/brussels_transit/compare/v0.1.2...v0.2.0)

**Implemented enhancements:**

- 🗺️ Add map-based stop explorer with dynamic loading [\#32](https://github.com/bdamokos/brussels_transit/issues/32)
- Add fallback to scheduled times [\#29](https://github.com/bdamokos/brussels_transit/issues/29)
- If agency.txt provides timezone info use it [\#26](https://github.com/bdamokos/brussels_transit/issues/26)

**Fixed bugs:**

- Log messages are doubled in the file logs [\#38](https://github.com/bdamokos/brussels_transit/issues/38)

**Merged pull requests:**

- Add realtime waiting times for SNCB [\#42](https://github.com/bdamokos/brussels_transit/pull/42) ([bdamokos](https://github.com/bdamokos))
- If agency.txt provides timezone info use it [\#41](https://github.com/bdamokos/brussels_transit/pull/41) ([bdamokos](https://github.com/bdamokos))
- Clean up logging [\#40](https://github.com/bdamokos/brussels_transit/pull/40) ([bdamokos](https://github.com/bdamokos))
- Add stops visible on the map in stop explorer [\#39](https://github.com/bdamokos/brussels_transit/pull/39) ([bdamokos](https://github.com/bdamokos))

## [v0.1.2](https://github.com/bdamokos/brussels_transit/tree/v0.1.2) (2024-12-30)

[Full Changelog](https://github.com/bdamokos/brussels_transit/compare/v0.1.1...v0.1.2)

**Implemented enhancements:**

- GTFS Data Explorer should allow searching by name or provider id [\#31](https://github.com/bdamokos/brussels_transit/issues/31)
- Add delete provider endpoint [\#30](https://github.com/bdamokos/brussels_transit/issues/30)
- BKK waiting times backend needs to be sped up [\#23](https://github.com/bdamokos/brussels_transit/issues/23)
- Expose schedule from the new frontend similarly as the real time schedule [\#21](https://github.com/bdamokos/brussels_transit/issues/21)
- Add waiting times endpoint to the backend [\#28](https://github.com/bdamokos/brussels_transit/pull/28) ([bdamokos](https://github.com/bdamokos))

**Fixed bugs:**

- Service days are returned in the wrong order [\#27](https://github.com/bdamokos/brussels_transit/issues/27)

## [v0.1.1](https://github.com/bdamokos/brussels_transit/tree/v0.1.1) (2024-12-26)

[Full Changelog](https://github.com/bdamokos/brussels_transit/compare/v0.1.0...v0.1.1)

**Merged pull requests:**

- Feature/precompiled-protobuf [\#25](https://github.com/bdamokos/brussels_transit/pull/25) ([bdamokos](https://github.com/bdamokos))

## [v0.1.0](https://github.com/bdamokos/brussels_transit/tree/v0.1.0) (2024-12-26)

[Full Changelog](https://github.com/bdamokos/brussels_transit/compare/3ebd8f30323eb5e27e326bad7244dcc160177557...v0.1.0)

**Fixed bugs:**

- 🐛 BKK config loading order not following expected precedence [\#17](https://github.com/bdamokos/brussels_transit/issues/17)
- BKK waiting times returning empty object [\#16](https://github.com/bdamokos/brussels_transit/issues/16)

**Merged pull requests:**

- 🐳 Add Docker publishing workflow [\#24](https://github.com/bdamokos/brussels_transit/pull/24) ([bdamokos](https://github.com/bdamokos))
- Feature/standardize config [\#22](https://github.com/bdamokos/brussels_transit/pull/22) ([bdamokos](https://github.com/bdamokos))
- Bump jinja2 from 3.1.4 to 3.1.5 in the pip group across 1 directory [\#14](https://github.com/bdamokos/brussels_transit/pull/14) ([dependabot[bot]](https://github.com/apps/dependabot))
- Add BKK \(Budapest Public Transport\) support to backend and frontend [\#13](https://github.com/bdamokos/brussels_transit/pull/13) ([bdamokos](https://github.com/bdamokos))
- 🚀 Add Schedule Explorer and Unified Start Script [\#12](https://github.com/bdamokos/brussels_transit/pull/12) ([bdamokos](https://github.com/bdamokos))
- Bump python-dateutil from 2.8.2 to 2.9.0.post0 [\#11](https://github.com/bdamokos/brussels_transit/pull/11) ([dependabot[bot]](https://github.com/apps/dependabot))
- Bump urllib3 from 2.2.3 to 2.3.0 [\#10](https://github.com/bdamokos/brussels_transit/pull/10) ([dependabot[bot]](https://github.com/apps/dependabot))
- Bump anyio from 4.6.2.post1 to 4.7.0 [\#9](https://github.com/bdamokos/brussels_transit/pull/9) ([dependabot[bot]](https://github.com/apps/dependabot))
- Bump orderly-set from 5.2.2 to 5.2.3 [\#8](https://github.com/bdamokos/brussels_transit/pull/8) ([dependabot[bot]](https://github.com/apps/dependabot))
- Bump apscheduler from 3.10.4 to 3.11.0 [\#7](https://github.com/bdamokos/brussels_transit/pull/7) ([dependabot[bot]](https://github.com/apps/dependabot))
- Bump click from 8.1.7 to 8.1.8 [\#6](https://github.com/bdamokos/brussels_transit/pull/6) ([dependabot[bot]](https://github.com/apps/dependabot))
- Bump certifi from 2024.8.30 to 2024.12.14 [\#5](https://github.com/bdamokos/brussels_transit/pull/5) ([dependabot[bot]](https://github.com/apps/dependabot))
- Bump jinja2 from 3.1.4 to 3.1.5 [\#4](https://github.com/bdamokos/brussels_transit/pull/4) ([dependabot[bot]](https://github.com/apps/dependabot))
- Bump numpy from 2.1.3 to 2.2.1 [\#3](https://github.com/bdamokos/brussels_transit/pull/3) ([dependabot[bot]](https://github.com/apps/dependabot))
- Bump httpx from 0.27.2 to 0.28.1 [\#2](https://github.com/bdamokos/brussels_transit/pull/2) ([dependabot[bot]](https://github.com/apps/dependabot))
- Bump deepdiff from 8.0.1 to 8.1.1 [\#1](https://github.com/bdamokos/brussels_transit/pull/1) ([dependabot[bot]](https://github.com/apps/dependabot))



\* *This Changelog was automatically generated by [github_changelog_generator](https://github.com/github-changelog-generator/github-changelog-generator)*
