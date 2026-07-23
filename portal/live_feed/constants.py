HUBS = {
    'apac': {'name': 'APAC', 'location': 'Asia Pacific'},
    'europe': {'name': 'Europe', 'location': 'Western Europe'},
    'middle-east': {'name': 'Middle East', 'location': 'Middle East'},
    'americas': {'name': 'Americas', 'location': 'North/South America'},
}

STATUS_KEY = 'live_feed:status'
STATUS_TTL_SECONDS = 30

COSTS_KEY = 'live_feed:costs:global'
COSTS_TTL_SECONDS = 24 * 60 * 60

COST_FIELDS = (
    'connects',
    'disconnects',
    'publishes',
    'broadcasts',
    'messages_sent',
    'messages_received',
)


def snapshot_key(hub: str) -> str:
    return f'live_feed:hub:{hub}:snapshot'


def items_key(hub: str) -> str:
    return f'live_feed:hub:{hub}:items'
