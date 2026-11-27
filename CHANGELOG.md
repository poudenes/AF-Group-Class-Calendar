# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project
uses [Semantic Versioning](https://semver.org/): `MAJOR.MINOR.PATCH`.

## [1.1.2] - 2026-11-27

### Changed
- The manifest lists the integration category *Calendars & to-dos*, so it can be found by
  category in HACS and the Home Assistant Marketplace.
- The HACS validation now also runs the brands check, using the bundled `brand/` icons.
- Releases are created automatically from a `vX.Y.Z` tag, with notes taken from this changelog.

## [1.1.1] - 2026-11-27

First public release.

### Added
- Reads the schedule image with any Home Assistant **AI Task** entity that supports images.
- Checks the image once a day; the AI is only called when the image changed.
- Two sources: the club website, or a media folder (Media → My media → Anytime Fitness) for club
  sites that block Home Assistant.
- Classes become weekly recurring events with room, instructor and footnotes; past weeks keep the
  schedule that applied then.
- Action `af_group_classes.refresh` to check now, force a re-read, or read a local image.
- English and Dutch translations.

### Fixed
- The first read could fail with "Unknown schedule" while Home Assistant was still finishing the
  setup.

[1.1.2]: https://github.com/poudenes/AF-Group-Class-Calendar/compare/v1.1.1...v1.1.2
[1.1.1]: https://github.com/poudenes/AF-Group-Class-Calendar/releases/tag/v1.1.1
