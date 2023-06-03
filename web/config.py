import os
import secrets

SECRET = os.getenv('SECRET', None)

if not SECRET:
    print('🚧 Warning: Environment variable SECRET is not set. Using a random value.')
    SECRET = secrets.token_bytes(32)

WEBSITE = os.getenv('WEBSITE', 'https://github.com/Zaczero/osm-relatify')

VERSION = '1.0'
CREATED_BY = f'osm-relatify {VERSION}'
USER_AGENT = f'osm-relatify/{VERSION} (+https://github.com/Zaczero/osm-relatify)'

# Dedicated instance unavailable? Pick one from the public list:
# https://wiki.openstreetmap.org/wiki/Overpass_API#Public_Overpass_API_instances
OVERPASS_API_INTERPRETER = os.getenv('OVERPASS_API_INTERPRETER', 'https://overpass.monicz.dev/api/interpreter')

TAG_MAX_LENGTH = 255

CONSUMER_KEY = os.getenv('CONSUMER_KEY', None)
CONSUMER_SECRET = os.getenv('CONSUMER_SECRET', None)

if not CONSUMER_KEY or not CONSUMER_SECRET:
    print('🚧 Warning: '
          'Environment variables CONSUMER_KEY and/or CONSUMER_SECRET are not set. '
          'You will not be able to authenticate with OpenStreetMap.')

CPU_COUNT = len(os.sched_getaffinity(0))
CALC_ROUTE_MAX_REQUESTS = 3
CALC_ROUTE_N_PROCESSES = max(1, CPU_COUNT // 4)
CALC_ROUTE_MAX_PROCESSES = CALC_ROUTE_N_PROCESSES * CALC_ROUTE_MAX_REQUESTS

CHANGESET_ID_PLACEHOLDER = f'__CHANGESET_ID_PLACEHOLDER__{secrets.token_urlsafe(8)}__'

DOWNLOAD_RELATION_WAY_BB_EXPAND = 250  # meters
DOWNLOAD_RELATION_GRID_SIZE = 0.01  # degrees
DOWNLOAD_RELATION_GRID_CELL_EXPAND = 0.001  # degrees, only used for internal calculations, not sent to the user

print(f'[CONF] {DOWNLOAD_RELATION_GRID_SIZE * 111_111 = :.0f} meters')
print(f'[CONF] {DOWNLOAD_RELATION_GRID_CELL_EXPAND * 111_111 = :.0f} meters')

BUS_COLLECTION_SEARCH_AREA = 50  # meters

assert DOWNLOAD_RELATION_GRID_CELL_EXPAND * 111_111 > BUS_COLLECTION_SEARCH_AREA
