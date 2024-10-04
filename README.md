# <img height="24" src="https://github.com/Zaczero/osm-relatify/blob/main/static/img/favicon/256.webp?raw=true" alt="🗺️"> OSM Relatify

![Python version](https://shields.monicz.dev/badge/python-v3.12-blue)
[![Liberapay Patrons](https://shields.monicz.dev/liberapay/patrons/Zaczero?logo=liberapay)](https://liberapay.com/Zaczero/)
[![GitHub Sponsors](https://shields.monicz.dev/github/sponsors/Zaczero?logo=github&label=Sponsors&color=%23db61a2)](https://github.com/sponsors/Zaczero)
[![GitHub repo stars](https://shields.monicz.dev/github/stars/Zaczero/osm-relatify?style=social)](https://github.com/Zaczero/osm-relatify)

OpenStreetMap public transport made easy.

You can access the **official instance** of osm-relatify at [relatify.monicz.dev](https://relatify.monicz.dev).

<img width="60%" src="https://github.com/Zaczero/osm-relatify/blob/main/resources/application-preview.png?raw=true" alt="Application preview">

## About

OSM Relatify is a user-friendly web application specifically designed for editing public transport relations within OpenStreetMap (OSM).

The application relies on the OSM data to be (more-or-less) accurately tagged. Incorrect or poor tagging may necessitate manual corrections using an OSM editor, like iD or JOSM.

Please note that, for now, OSM Relatify only supports **bus** and **tram** relations.

## User documentation

<https://wiki.openstreetmap.org/wiki/Relatify>

## Features

### Supported

- ✅ Bus routes
- ✅ Tram routes
- ✅ One-way roads
- ✅ Roundabouts
- ✅ Right-hand traffic
- ✅ `ref` & `local_ref`
- ✅ `roundtrip`
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
- ⏳ Trolleybuses, trains, etc.

### Unsupported

- ❌ Exceptionally poor tagging
- ❌ `public_transport:version=1`
