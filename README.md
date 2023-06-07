# <img height="24" src="https://github.com/Zaczero/osm-relatify/blob/main/web/static/img/icon.png?raw=true" alt="🗺️"> OSM Relatify

![Python version](https://img.shields.io/badge/python-v3.11-blue)
[![GitHub](https://img.shields.io/github/license/Zaczero/osm-relatify)](https://github.com/Zaczero/osm-relatify/blob/main/LICENSE)
[![GitHub repo stars](https://img.shields.io/github/stars/Zaczero/osm-relatify?style=social)](https://github.com/Zaczero/osm-relatify)

OpenStreetMap public transport made easy.

You can access the **official instance** of osm-relatify at [relatify.monicz.dev](https://relatify.monicz.dev).

## About

OSM Relatify is a user-friendly web application specifically designed for editing public transport relations within OpenStreetMap (OSM).

The application relies on the OSM data to be (more-or-less) accurately tagged. Incorrect or poor tagging may necessitate manual corrections using an OSM editor, like iD or JOSM.

Please note that, for now, OSM Relatify only supports bus relations.

## Features

### Supported

- ✅ Bus routes
- ✅ One-way streets
- ✅ Roundabouts
- ✅ Right-hand traffic
- ✅ `public_transport:version=2`
- ✅ `public_transport=platform`
- ✅ `public_transport=stop_position`
- ✅ `public_transport=stop_area`

### Planned

- ⏳ Custom changeset comment
- ⏳ Tag editing
- ⏳ Creating new relations
- ⏳ Creating new bus stops
- ⏳ Left-hand traffic
- ⏳ Relation `type=restriction`
- ⏳ `direction=*`
- ⏳ `oneway=-1`
- ⏳ Trams, trolleybuses, trains, etc.

### Unsupported

- ❌ Exceptionally poor tagging
- ❌ `public_transport:version=1`

## Footer

### Contact

- Email: [kamil@monicz.pl](mailto:kamil@monicz.pl)
- LinkedIn: [linkedin.com/in/kamil-monicz](https://www.linkedin.com/in/kamil-monicz/)

### License

This project is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0).

You can find the full text of the license in the repository at [LICENSE](https://github.com/Zaczero/osm-revert/blob/main/LICENSE).
