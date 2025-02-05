import os
import secrets

import sentry_sdk
from githead import githead

VERSION = 'git#' + githead()[:7]
WEBSITE = os.getenv('WEBSITE', 'https://github.com/Zaczero/osm-relatify')
CREATED_BY = f'osm-relatify {VERSION}'
USER_AGENT = f'osm-relatify/{VERSION} (+https://github.com/Zaczero/osm-relatify)'

TEST_ENV = os.getenv('TEST_ENV', '0').strip().lower() in ('1', 'true', 'yes')
if TEST_ENV:
    print('[CONF] Running in test environment')

# Dedicated instance unavailable? Pick one from the public list:
# https://wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances
OVERPASS_API_INTERPRETER = os.getenv('OVERPASS_API_INTERPRETER', 'https://overpass-api.de/api/interpreter')

TAG_MAX_LENGTH = 255

OSM_CLIENT = os.getenv('OSM_CLIENT', None)
OSM_SECRET = os.getenv('OSM_SECRET', None)
OSM_SCOPES = 'read_prefs write_api'

if not OSM_CLIENT or not OSM_SECRET:
    print(
        '🚧 Warning: '
        'Environment variables OSM_CLIENT and/or OSM_SECRET are not set. '
        'You will not be able to authenticate with OpenStreetMap.'
    )

CALC_ROUTE_MAX_REQUESTS = 3
CALC_ROUTE_N_PROCESSES = max(1, os.process_cpu_count() // 4)
CALC_ROUTE_MAX_PROCESSES = CALC_ROUTE_MAX_REQUESTS * CALC_ROUTE_N_PROCESSES
CALC_ROUTE_TASKS_PER_PROCESS = 1000

CHANGESET_ID_PLACEHOLDER = f'__CHANGESET_ID_PLACEHOLDER__{secrets.token_urlsafe(8)}__'

DOWNLOAD_RELATION_WAY_BB_EXPAND = 250  # meters
DOWNLOAD_RELATION_GRID_SIZE = 0.01  # degrees
DOWNLOAD_RELATION_GRID_CELL_EXPAND = 0.001  # degrees, only used for internal calculations, not sent to the user

print(f'[CONF] {DOWNLOAD_RELATION_GRID_SIZE * 111_111 = :.0f} meters')
print(f'[CONF] {DOWNLOAD_RELATION_GRID_CELL_EXPAND * 111_111 = :.0f} meters')

BUS_COLLECTION_SEARCH_AREA = 50  # meters

assert DOWNLOAD_RELATION_GRID_CELL_EXPAND * 111_111 > BUS_COLLECTION_SEARCH_AREA * 2

if SENTRY_DSN := os.getenv('SENTRY_DSN'):
    sentry_sdk.init(
        dsn=SENTRY_DSN,
        release=VERSION,
        enable_tracing=True,
        traces_sample_rate=0.3,
        trace_propagation_targets=None,
        profiles_sample_rate=0.2,
    )
