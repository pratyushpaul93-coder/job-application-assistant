import json, urllib.request, os, datetime, sys

WORKSPACE = '/root/pp-jobapp/workspace'
SCRIPTS = '/root/pp-jobapp/scripts'
CONFIG_PATH = SCRIPTS + '/scout_config.json'
DB_PATH = WORKSPACE + '/jobapp.db'

# ============================================================
# Load config from JSON. Edit scout_config.json to tune Scout.
# ============================================================

if not os.path.exists(CONFIG_PATH):
    print("FATAL: Config file not found at " + CONFIG_PATH)
    sys.exit(1)

with open(CONFIG_PATH) as f:
    CONFIG = json.load(f)

TITLE_POSITIVE = [k.lower() for k in CONFIG['title_patterns_positive']]
TITLE_NEGATIVE = [k.lower() for k in CONFIG['title_patterns_negative']]
JD_FALLBACK_PHRASES = [k.lower() for k in CONFIG.get('jd_fallback_phrases', [])]
SETTINGS = CONFIG.get('scout_settings', {})
JD_FALLBACK_ENABLED = SETTINGS.get('jd_fallback_enabled', True)
JD_CAP = SETTINGS.get('jd_text_cap_chars', 4000)

# ============================================================
# Company list (preserved from v1)
# ============================================================

COMPANIES = [
    {'name': 'Ramp', 'ats': 'ashby', 'slug': 'ramp', 'stage': 'Series D+', 'vertical': 'Fintech'},
    {'name': 'Notion', 'ats': 'ashby', 'slug': 'notion', 'stage': 'Series C', 'vertical': 'SaaS'},
    {'name': 'Vanta', 'ats': 'ashby', 'slug': 'vanta', 'stage': 'Series C', 'vertical': 'SaaS'},
    {'name': 'Harvey', 'ats': 'ashby', 'slug': 'harvey', 'stage': 'Series C', 'vertical': 'AI'},
    {'name': 'ElevenLabs', 'ats': 'ashby', 'slug': 'elevenlabs', 'stage': 'Series C', 'vertical': 'AI'},
    {'name': 'Cohere', 'ats': 'ashby', 'slug': 'cohere', 'stage': 'Series D', 'vertical': 'AI'},
    {'name': 'LangChain', 'ats': 'ashby', 'slug': 'langchain', 'stage': 'Series A', 'vertical': 'AI'},
    {'name': 'Pinecone', 'ats': 'ashby', 'slug': 'pinecone', 'stage': 'Series B', 'vertical': 'AI'},
    {'name': 'Sierra', 'ats': 'ashby', 'slug': 'sierra', 'stage': 'Series B', 'vertical': 'AI'},
    {'name': 'Linear', 'ats': 'ashby', 'slug': 'linear', 'stage': 'Series B', 'vertical': 'SaaS'},
    {'name': 'Zapier', 'ats': 'ashby', 'slug': 'zapier', 'stage': 'Bootstrapped', 'vertical': 'SaaS'},
    {'name': 'n8n', 'ats': 'ashby', 'slug': 'n8n', 'stage': 'Series B', 'vertical': 'SaaS'},
    {'name': 'Glean', 'ats': 'greenhouse', 'slug': 'gleanwork', 'stage': 'Series E', 'vertical': 'AI'},
    {'name': 'Brex', 'ats': 'greenhouse', 'slug': 'brex', 'stage': 'Series D', 'vertical': 'Fintech'},
    {'name': 'Cyera', 'ats': 'broken', 'slug': 'cyera', 'stage': 'Series C', 'vertical': 'SaaS'},
    {'name': 'Airtable', 'ats': 'greenhouse', 'slug': 'airtable', 'stage': 'Series F', 'vertical': 'SaaS'},
    {'name': 'Vercel', 'ats': 'greenhouse', 'slug': 'vercel', 'stage': 'Series D', 'vertical': 'AI'},
    {'name': 'Intercom', 'ats': 'greenhouse', 'slug': 'intercom', 'stage': 'Public', 'vertical': 'SaaS'},
    {'name': 'Anthropic', 'ats': 'greenhouse', 'slug': 'anthropic', 'stage': 'Series E', 'vertical': 'AI'},
    {'name': 'Wiz', 'ats': 'broken', 'slug': 'wizsecurity', 'stage': 'Series E', 'vertical': 'SaaS'},
    {'name': 'Figma', 'ats': 'greenhouse', 'slug': 'figma', 'stage': 'Public', 'vertical': 'SaaS'},
    {'name': 'Mistral', 'ats': 'ashby', 'slug': 'mistral', 'stage': 'Series B', 'vertical': 'AI'},
    {'name': 'Weights & Biases', 'ats': 'broken', 'slug': 'wandb', 'stage': 'Series C', 'vertical': 'AI'},
    {'name': 'Spotify', 'ats': 'lever', 'slug': 'spotify', 'stage': 'Public', 'vertical': 'Marketplace'},
    {'name': 'Rippling', 'ats': 'tavily', 'slug': 'rippling', 'stage': 'Series F', 'vertical': 'SaaS'},
    {'name': 'kalshi', 'ats': 'ashby', 'slug': 'kalshi', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'spoton', 'ats': 'ashby', 'slug': 'spoton', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'tanium', 'ats': 'greenhouse', 'slug': 'tanium', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'lime', 'ats': 'broken', 'slug': 'Lime', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'mirage', 'ats': 'ashby', 'slug': 'mirage', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'pearl health', 'ats': 'ashby', 'slug': 'pearlhealth', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'waymo', 'ats': 'greenhouse', 'slug': 'waymo', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'hedra', 'ats': 'ashby', 'slug': 'hedra', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'talos', 'ats': 'ashby', 'slug': 'talos-trading', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'hyperexponential', 'ats': 'ashby', 'slug': 'hyperexponential', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'heron power', 'ats': 'ashby', 'slug': 'heron-power', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'sesame', 'ats': 'ashby', 'slug': 'sesame', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Ambient', 'ats': 'ashby', 'slug': 'ambient.ai', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Tennr', 'ats': 'ashby', 'slug': 'tennr', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'everlaw', 'ats': 'greenhouse', 'slug': 'everlaw', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'clickup', 'ats': 'ashby', 'slug': 'clickup', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'talkiatry', 'ats': 'ashby', 'slug': 'talkiatry', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'gamma', 'ats': 'ashby', 'slug': 'gamma', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'sentilink', 'ats': 'ashby', 'slug': 'sentilink', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': '0x', 'ats': 'ashby', 'slug': '0x', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': '2U', 'ats': 'greenhouse', 'slug': '2u', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Abacus', 'ats': 'greenhouse', 'slug': 'abacus', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Abridge', 'ats': 'ashby', 'slug': 'abridge', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Adaptive', 'ats': 'ashby', 'slug': 'adaptive', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Adaptive Security', 'ats': 'ashby', 'slug': 'adaptivesecurity', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Addi', 'ats': 'ashby', 'slug': 'addi', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Affirm', 'ats': 'greenhouse', 'slug': 'affirm', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Aghanim', 'ats': 'ashby', 'slug': 'aghanim', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Airbnb', 'ats': 'greenhouse', 'slug': 'airbnb', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'AirGarage', 'ats': 'ashby', 'slug': 'airgarage', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Aiwyn', 'ats': 'ashby', 'slug': 'aiwyn', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'AKASA', 'ats': 'ashby', 'slug': 'akasa', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Alchemy', 'ats': 'ashby', 'slug': 'alchemy', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Alloy', 'ats': 'greenhouse', 'slug': 'alloy', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Alluxio', 'ats': 'lever', 'slug': 'alluxio', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Amber', 'ats': 'ashby', 'slug': 'amber', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Amperos', 'ats': 'ashby', 'slug': 'amperos', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Amplitude', 'ats': 'greenhouse', 'slug': 'amplitude', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Anchorage', 'ats': 'lever', 'slug': 'anchorage', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Ansible Health', 'ats': 'ashby', 'slug': 'ansiblehealth', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'ANYbotics', 'ats': 'lever', 'slug': 'anybotics', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'AnyRoad', 'ats': 'lever', 'slug': 'anyroad', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Anyscale', 'ats': 'ashby', 'slug': 'anyscale', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Anything', 'ats': 'ashby', 'slug': 'anything', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Apollo', 'ats': 'greenhouse', 'slug': 'apollo', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Applied Intuition', 'ats': 'greenhouse', 'slug': 'appliedintuition', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Apron', 'ats': 'ashby', 'slug': 'apron', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Archy', 'ats': 'ashby', 'slug': 'archy', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Asana', 'ats': 'greenhouse', 'slug': 'asana', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Asimov', 'ats': 'ashby', 'slug': 'asimov', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Astranis', 'ats': 'greenhouse', 'slug': 'astranis', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Astro Mechanica', 'ats': 'ashby', 'slug': 'astro-mechanica', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'August', 'ats': 'ashby', 'slug': 'august', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Auterion', 'ats': 'greenhouse', 'slug': 'auterion', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Axion', 'ats': 'ashby', 'slug': 'axion', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Axonius', 'ats': 'greenhouse', 'slug': 'axonius', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Azra Games', 'ats': 'greenhouse', 'slug': 'azragames', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Bankjoy', 'ats': 'ashby', 'slug': 'bankjoy', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Basis', 'ats': 'ashby', 'slug': 'basis-ai', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Bastion', 'ats': 'ashby', 'slug': 'bastion', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Bayesian Health', 'ats': 'ashby', 'slug': 'bayesianhealth', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Believer', 'ats': 'ashby', 'slug': 'believer', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Belong', 'ats': 'lever', 'slug': 'belong', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Benchling', 'ats': 'ashby', 'slug': 'benchling', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Betterment', 'ats': 'greenhouse', 'slug': 'betterment', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Beyond', 'ats': 'greenhouse', 'slug': 'beyond', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'BigID', 'ats': 'greenhouse', 'slug': 'bigid', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Black Forest Labs', 'ats': 'greenhouse', 'slug': 'blackforestlabs', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Bold', 'ats': 'greenhouse', 'slug': 'bold', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Bold Metrics', 'ats': 'greenhouse', 'slug': 'boldmetrics', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Bonfire Studios', 'ats': 'greenhouse', 'slug': 'bonfirestudios', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Bounce', 'ats': 'ashby', 'slug': 'bounce', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Branch', 'ats': 'greenhouse', 'slug': 'branch', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Breaker', 'ats': 'ashby', 'slug': 'breaker', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Brightwheel', 'ats': 'ashby', 'slug': 'brightwheel', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Brisk Teaching', 'ats': 'ashby', 'slug': 'brisk-teaching', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'BuzzFeed', 'ats': 'greenhouse', 'slug': 'buzzfeed', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Cambly', 'ats': 'ashby', 'slug': 'cambly', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Cape', 'ats': 'ashby', 'slug': 'cape', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Capitolis', 'ats': 'greenhouse', 'slug': 'capitolis', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'CaptivateIQ', 'ats': 'lever', 'slug': 'captivateiq', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Carwow', 'ats': 'ashby', 'slug': 'carwow', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Cedar', 'ats': 'ashby', 'slug': 'cedar', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Cents', 'ats': 'lever', 'slug': 'cents', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Charthop', 'ats': 'ashby', 'slug': 'charthop', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Chestnut', 'ats': 'ashby', 'slug': 'chestnut', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Choco', 'ats': 'ashby', 'slug': 'choco', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'CircuitHub', 'ats': 'ashby', 'slug': 'circuithub', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Clarity', 'ats': 'ashby', 'slug': 'clarity', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Clerk', 'ats': 'ashby', 'slug': 'clerk', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Clever', 'ats': 'greenhouse', 'slug': 'clever', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'ClickHouse', 'ats': 'greenhouse', 'slug': 'clickhouse', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Clipboard', 'ats': 'ashby', 'slug': 'clipboard', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Cloudinary', 'ats': 'lever', 'slug': 'cloudinary', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Clubhouse', 'ats': 'ashby', 'slug': 'clubhouse', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Clutch', 'ats': 'greenhouse', 'slug': 'clutch', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Coder', 'ats': 'ashby', 'slug': 'coder', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Coinbase', 'ats': 'greenhouse', 'slug': 'coinbase', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Compound', 'ats': 'ashby', 'slug': 'compound', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'CopilotIQ', 'ats': 'greenhouse', 'slug': 'copilotiq', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Cresta', 'ats': 'greenhouse', 'slug': 'cresta', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Crete Professionals Alliance', 'ats': 'ashby', 'slug': 'crete-professionals-alliance', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Cross River Bank', 'ats': 'greenhouse', 'slug': 'crossriverbank', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Curri', 'ats': 'ashby', 'slug': 'curri', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Cyngn', 'ats': 'lever', 'slug': 'cyngn', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Dashlane', 'ats': 'greenhouse', 'slug': 'dashlane', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Databook', 'ats': 'ashby', 'slug': 'databook', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Databricks', 'ats': 'greenhouse', 'slug': 'databricks', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Daylight', 'ats': 'greenhouse', 'slug': 'daylight', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Decagon', 'ats': 'ashby', 'slug': 'decagon', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Deel', 'ats': 'ashby', 'slug': 'deel', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'DeepL', 'ats': 'ashby', 'slug': 'deepl', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Descript', 'ats': 'greenhouse', 'slug': 'descript', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Dialpad', 'ats': 'greenhouse', 'slug': 'dialpad', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'DISCO', 'ats': 'greenhouse', 'slug': 'disco', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Discord', 'ats': 'greenhouse', 'slug': 'discord', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Dispatch', 'ats': 'ashby', 'slug': 'dispatch', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Dollar Shave Club', 'ats': 'greenhouse', 'slug': 'dollarshaveclub', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Doppel', 'ats': 'ashby', 'slug': 'doppel', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Doxel', 'ats': 'lever', 'slug': 'doxel', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'DroneDeploy', 'ats': 'lever', 'slug': 'dronedeploy', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Earli', 'ats': 'greenhouse', 'slug': 'earli', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Earnest', 'ats': 'greenhouse', 'slug': 'earnest', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Earnin', 'ats': 'greenhouse', 'slug': 'earnin', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Electric', 'ats': 'ashby', 'slug': 'electric', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'EliseAI', 'ats': 'ashby', 'slug': 'eliseai', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'End Game', 'ats': 'ashby', 'slug': 'endgame', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Engflow', 'ats': 'ashby', 'slug': 'engflow', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Envoy', 'ats': 'ashby', 'slug': 'envoy', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Erasca', 'ats': 'greenhouse', 'slug': 'erasca', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Espresso', 'ats': 'ashby', 'slug': 'espresso', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Eve', 'ats': 'greenhouse', 'slug': 'eve', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Exowatt', 'ats': 'lever', 'slug': 'exowatt', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Eye Security', 'ats': 'ashby', 'slug': 'eye-security', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Fandom', 'ats': 'greenhouse', 'slug': 'fandom', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'favorited', 'ats': 'ashby', 'slug': 'favorited', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Fieldguide', 'ats': 'ashby', 'slug': 'fieldguide', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Filmhub', 'ats': 'ashby', 'slug': 'filmhub', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Fivetran', 'ats': 'greenhouse', 'slug': 'fivetran', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Flexport', 'ats': 'greenhouse', 'slug': 'flexport', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Flock Homes', 'ats': 'greenhouse', 'slug': 'flockhomes', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Folx Health', 'ats': 'greenhouse', 'slug': 'folxhealth', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Formation Bio', 'ats': 'greenhouse', 'slug': 'formationbio', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Forter', 'ats': 'greenhouse', 'slug': 'forter', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Fortuna Health', 'ats': 'ashby', 'slug': 'fortuna-health', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Forward Networks', 'ats': 'greenhouse', 'slug': 'forwardnetworks', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Foundation', 'ats': 'ashby', 'slug': 'foundation', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Foursquare', 'ats': 'ashby', 'slug': 'foursquare', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Foxglove', 'ats': 'ashby', 'slug': 'foxglove', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Freenome', 'ats': 'greenhouse', 'slug': 'freenome', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Fulcrum', 'ats': 'ashby', 'slug': 'fulcrum', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Genius', 'ats': 'broken', 'slug': 'genius', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Gensyn', 'ats': 'greenhouse', 'slug': 'gensyn', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'GigFinesse', 'ats': 'greenhouse', 'slug': 'gigfinesse', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'GlossGenius', 'ats': 'greenhouse', 'slug': 'glossgenius', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'GoodData', 'ats': 'ashby', 'slug': 'gooddata', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Graphite', 'ats': 'ashby', 'slug': 'graphite', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Greenlight', 'ats': 'lever', 'slug': 'greenlight', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Groupon', 'ats': 'greenhouse', 'slug': 'groupon', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Guild', 'ats': 'ashby', 'slug': 'guild', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Gusto', 'ats': 'greenhouse', 'slug': 'gusto', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Halliday', 'ats': 'ashby', 'slug': 'halliday', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Halter', 'ats': 'ashby', 'slug': 'halter', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Hatch', 'ats': 'ashby', 'slug': 'hatch', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Headway', 'ats': 'greenhouse', 'slug': 'headway', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'HealthSherpa', 'ats': 'ashby', 'slug': 'healthsherpa', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Hebbia', 'ats': 'ashby', 'slug': 'hebbia-ai', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Hinge Health', 'ats': 'ashby', 'slug': 'hinge-health', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'HockeyStack', 'ats': 'ashby', 'slug': 'hockeystack', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Honor', 'ats': 'greenhouse', 'slug': 'honor', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'House Rx', 'ats': 'greenhouse', 'slug': 'houserx', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Hyperscience', 'ats': 'ashby', 'slug': 'hyperscience', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Ideogram', 'ats': 'ashby', 'slug': 'ideogram', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Illumio', 'ats': 'ashby', 'slug': 'illumio', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Imply', 'ats': 'greenhouse', 'slug': 'imply', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Improbable', 'ats': 'ashby', 'slug': 'improbable', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Inceptive', 'ats': 'greenhouse', 'slug': 'inceptive', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Incognia', 'ats': 'greenhouse', 'slug': 'incognia', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Inductive Bio', 'ats': 'ashby', 'slug': 'inductive-bio', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Inertia', 'ats': 'ashby', 'slug': 'inertia', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Inngest', 'ats': 'ashby', 'slug': 'inngest', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'insitro', 'ats': 'ashby', 'slug': 'insitro', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Instabase', 'ats': 'greenhouse', 'slug': 'instabase', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Instacart', 'ats': 'greenhouse', 'slug': 'instacart', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Instructure', 'ats': 'ashby', 'slug': 'instructure', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Intro', 'ats': 'ashby', 'slug': 'intro', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Jumio', 'ats': 'greenhouse', 'slug': 'jumio', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'k-ID', 'ats': 'ashby', 'slug': 'k-id', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Kaizen Labs', 'ats': 'ashby', 'slug': 'kaizenlabs', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Kindred', 'ats': 'ashby', 'slug': 'kindred', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Knownwell', 'ats': 'ashby', 'slug': 'knownwell', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'KoBold Metals', 'ats': 'greenhouse', 'slug': 'koboldmetals', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Kodex', 'ats': 'ashby', 'slug': 'kodex', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Komodo Health', 'ats': 'greenhouse', 'slug': 'komodohealth', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Kong', 'ats': 'ashby', 'slug': 'kong', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Kroll Bond Rating Agency', 'ats': 'greenhouse', 'slug': 'krollbondratingagency', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Kymera Therapeutics', 'ats': 'greenhouse', 'slug': 'kymeratherapeutics', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Labelbox', 'ats': 'greenhouse', 'slug': 'labelbox', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'LaunchDarkly', 'ats': 'greenhouse', 'slug': 'launchdarkly', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Legora', 'ats': 'ashby', 'slug': 'legora', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Life360', 'ats': 'greenhouse', 'slug': 'life360', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Lightspark', 'ats': 'ashby', 'slug': 'lightspark', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'LinkedIn', 'ats': 'greenhouse', 'slug': 'linkedin', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Lithic', 'ats': 'greenhouse', 'slug': 'lithic', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Litify', 'ats': 'greenhouse', 'slug': 'litify', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Lookout', 'ats': 'greenhouse', 'slug': 'lookout', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'LTSE', 'ats': 'greenhouse', 'slug': 'ltse', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Lumos', 'ats': 'ashby', 'slug': 'lumos', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Luxury Presence', 'ats': 'lever', 'slug': 'luxurypresence', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Lyft', 'ats': 'greenhouse', 'slug': 'lyft', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Magic Leap', 'ats': 'greenhouse', 'slug': 'magicleap', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'MaintainX', 'ats': 'greenhouse', 'slug': 'maintainx', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Manychat', 'ats': 'greenhouse', 'slug': 'manychat', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Material Security', 'ats': 'ashby', 'slug': 'materialsecurity', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Matik', 'ats': 'greenhouse', 'slug': 'matik', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Maven', 'ats': 'ashby', 'slug': 'maven', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Maze Therapeutics', 'ats': 'greenhouse', 'slug': 'mazetherapeutics', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Medium', 'ats': 'greenhouse', 'slug': 'medium', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Mem', 'ats': 'ashby', 'slug': 'mem', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Mercury', 'ats': 'greenhouse', 'slug': 'mercury', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Metronome', 'ats': 'greenhouse', 'slug': 'metronome', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Mind Robotics', 'ats': 'ashby', 'slug': 'mindrobotics', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Mindbody', 'ats': 'greenhouse', 'slug': 'mindbody', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Mintlify', 'ats': 'ashby', 'slug': 'mintlify', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Miter', 'ats': 'ashby', 'slug': 'miter', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Mixpanel', 'ats': 'greenhouse', 'slug': 'mixpanel', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'ModernFi', 'ats': 'ashby', 'slug': 'modernfi', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Moment', 'ats': 'ashby', 'slug': 'moment', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Motherduck', 'ats': 'ashby', 'slug': 'motherduck', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Mural Health', 'ats': 'greenhouse', 'slug': 'muralhealth', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Mux', 'ats': 'ashby', 'slug': 'mux', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'MyHeritage', 'ats': 'greenhouse', 'slug': 'myheritage', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Mysten Labs', 'ats': 'ashby', 'slug': 'mystenlabs', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Nansen', 'ats': 'greenhouse', 'slug': 'nansen', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Nash', 'ats': 'ashby', 'slug': 'nash', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Neighbor', 'ats': 'lever', 'slug': 'neighbor', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Netlify', 'ats': 'greenhouse', 'slug': 'netlify', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'NeueHealth', 'ats': 'greenhouse', 'slug': 'neuehealth', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Nitra', 'ats': 'lever', 'slug': 'nitra', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'NODA AI', 'ats': 'ashby', 'slug': 'noda-ai', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Northwood Space', 'ats': 'ashby', 'slug': 'northwoodspace', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Octant Bio', 'ats': 'greenhouse', 'slug': 'octantbio', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Odyssey', 'ats': 'ashby', 'slug': 'odyssey', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'OfferUp', 'ats': 'greenhouse', 'slug': 'offerup', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Okta', 'ats': 'greenhouse', 'slug': 'okta', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Omada Health', 'ats': 'greenhouse', 'slug': 'omadahealth', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'OnXMaps', 'ats': 'greenhouse', 'slug': 'onxmaps', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'OpenAI', 'ats': 'ashby', 'slug': 'openai', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Opendoor', 'ats': 'greenhouse', 'slug': 'opendoor', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'OpenGov', 'ats': 'ashby', 'slug': 'opengov', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'OpenSea', 'ats': 'ashby', 'slug': 'opensea', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Optimal Dynamics', 'ats': 'greenhouse', 'slug': 'optimaldynamics', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Orbit', 'ats': 'ashby', 'slug': 'orbit', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Orchestra Bio', 'ats': 'ashby', 'slug': 'orchestra-bio', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Oshi Health', 'ats': 'greenhouse', 'slug': 'oshihealth', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Otter', 'ats': 'greenhouse', 'slug': 'otter', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'PagerDuty', 'ats': 'greenhouse', 'slug': 'pagerduty', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Patch', 'ats': 'greenhouse', 'slug': 'patch', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Payrails', 'ats': 'ashby', 'slug': 'payrails', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'People.ai', 'ats': 'lever', 'slug': 'people-ai', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Perplexity', 'ats': 'ashby', 'slug': 'perplexity', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Phantom', 'ats': 'ashby', 'slug': 'phantom', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Pindrop Security', 'ats': 'greenhouse', 'slug': 'pindropsecurity', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Pinterest', 'ats': 'greenhouse', 'slug': 'pinterest', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Pipedrive', 'ats': 'lever', 'slug': 'pipedrive', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Pivotal Health', 'ats': 'ashby', 'slug': 'pivotal-health', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Plaid', 'ats': 'ashby', 'slug': 'plaid', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'PlanetScale', 'ats': 'greenhouse', 'slug': 'planetscale', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Point', 'ats': 'lever', 'slug': 'getpoint', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Pomelo Care', 'ats': 'greenhouse', 'slug': 'pomelocare', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Prefect', 'ats': 'ashby', 'slug': 'prefect', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Preql', 'ats': 'ashby', 'slug': 'preql', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'PROOF', 'ats': 'greenhouse', 'slug': 'proof', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Proof of Play', 'ats': 'ashby', 'slug': 'proofofplay', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Propel', 'ats': 'ashby', 'slug': 'propel', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Quantifind', 'ats': 'greenhouse', 'slug': 'quantifind', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Quora', 'ats': 'ashby', 'slug': 'quora', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Qventus', 'ats': 'greenhouse', 'slug': 'qventus', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Rasa', 'ats': 'ashby', 'slug': 'rasa', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Reddit', 'ats': 'greenhouse', 'slug': 'reddit', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Regrello', 'ats': 'lever', 'slug': 'regrello', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Reltio', 'ats': 'greenhouse', 'slug': 'reltio', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Repl.it', 'ats': 'ashby', 'slug': 'replit', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Rescale', 'ats': 'ashby', 'slug': 'rescale', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Resend', 'ats': 'ashby', 'slug': 'resend', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Restream', 'ats': 'ashby', 'slug': 'restream', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Rho', 'ats': 'ashby', 'slug': 'rho', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Ripple', 'ats': 'greenhouse', 'slug': 'ripple', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Robinhood', 'ats': 'greenhouse', 'slug': 'robinhood', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Roblox', 'ats': 'greenhouse', 'slug': 'roblox', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Rocket Lab', 'ats': 'greenhouse', 'slug': 'rocketlab', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Runloop', 'ats': 'ashby', 'slug': 'runloop', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Runway', 'ats': 'ashby', 'slug': 'runway', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Rutter', 'ats': 'ashby', 'slug': 'rutter', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Samsara', 'ats': 'greenhouse', 'slug': 'samsara', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Sandbox VR', 'ats': 'lever', 'slug': 'sandboxvr', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Sardine', 'ats': 'ashby', 'slug': 'sardine', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Saviynt', 'ats': 'lever', 'slug': 'saviynt', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Scopely', 'ats': 'greenhouse', 'slug': 'scopely', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Sequence', 'ats': 'ashby', 'slug': 'sequence', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Series AI', 'ats': 'ashby', 'slug': 'seriesai', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Shield AI', 'ats': 'lever', 'slug': 'shieldai', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Singularity6', 'ats': 'greenhouse', 'slug': 'singularity6', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Sirona Medical', 'ats': 'greenhouse', 'slug': 'sironamedical', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Sisense', 'ats': 'greenhouse', 'slug': 'sisense', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Sky Mavis', 'ats': 'ashby', 'slug': 'skymavis', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Skydio', 'ats': 'ashby', 'slug': 'skydio', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Skysafe', 'ats': 'lever', 'slug': 'skysafe', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Sleeper', 'ats': 'ashby', 'slug': 'sleeper', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Slice', 'ats': 'greenhouse', 'slug': 'slice', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Slingshot AI', 'ats': 'ashby', 'slug': 'slingshotai', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'SmartAsset', 'ats': 'greenhouse', 'slug': 'smartasset', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Smartling', 'ats': 'greenhouse', 'slug': 'smartling', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Snackpass', 'ats': 'ashby', 'slug': 'snackpass', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Snaplogic', 'ats': 'lever', 'slug': 'snaplogic', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Socket', 'ats': 'ashby', 'slug': 'socket', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'SpaceX', 'ats': 'greenhouse', 'slug': 'spacex', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Spade', 'ats': 'greenhouse', 'slug': 'spade', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Sprig', 'ats': 'ashby', 'slug': 'sprig', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Sprinter Health', 'ats': 'ashby', 'slug': 'sprinter-health', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Stacker', 'ats': 'ashby', 'slug': 'stacker', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Starburst', 'ats': 'greenhouse', 'slug': 'starburst', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Stelo', 'ats': 'greenhouse', 'slug': 'stelo', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Stensul', 'ats': 'greenhouse', 'slug': 'stensul', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Stripe', 'ats': 'greenhouse', 'slug': 'stripe', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Stytch', 'ats': 'ashby', 'slug': 'stytch', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Submittable', 'ats': 'greenhouse', 'slug': 'submittable', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Substack', 'ats': 'ashby', 'slug': 'substack', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Supermove', 'ats': 'lever', 'slug': 'supermove', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Svix', 'ats': 'ashby', 'slug': 'svix', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Swan', 'ats': 'ashby', 'slug': 'swan', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Tandem', 'ats': 'ashby', 'slug': 'tandem', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Theorycraft Games', 'ats': 'lever', 'slug': 'theorycraftgames', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'ThirdLove', 'ats': 'greenhouse', 'slug': 'thirdlove', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Thread', 'ats': 'ashby', 'slug': 'thread-ai', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Thunes', 'ats': 'greenhouse', 'slug': 'thunes', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Thyme Care', 'ats': 'ashby', 'slug': 'thyme-care', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Tilt', 'ats': 'ashby', 'slug': 'tilt', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'TipTop', 'ats': 'greenhouse', 'slug': 'tiptop', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Titan', 'ats': 'ashby', 'slug': 'titan', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Toast', 'ats': 'greenhouse', 'slug': 'toast', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Tonal', 'ats': 'ashby', 'slug': 'tonal', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'TripleLift', 'ats': 'greenhouse', 'slug': 'triplelift', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'TruckSmarter', 'ats': 'ashby', 'slug': 'trucksmarter', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'True Link Financial', 'ats': 'ashby', 'slug': 'truelinkfinancial', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Truffle Security', 'ats': 'greenhouse', 'slug': 'trufflesecurity', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Twilio', 'ats': 'greenhouse', 'slug': 'twilio', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Twitch', 'ats': 'greenhouse', 'slug': 'twitch', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Udacity', 'ats': 'greenhouse', 'slug': 'udacity', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Udemy', 'ats': 'greenhouse', 'slug': 'udemy', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Udio', 'ats': 'greenhouse', 'slug': 'udio', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Ultima Genomics', 'ats': 'greenhouse', 'slug': 'ultimagenomics', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Uniswap', 'ats': 'ashby', 'slug': 'uniswap', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Unite Us', 'ats': 'greenhouse', 'slug': 'uniteus', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Universal', 'ats': 'greenhouse', 'slug': 'universal', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Valon', 'ats': 'ashby', 'slug': 'valon', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Vantage', 'ats': 'ashby', 'slug': 'vantage', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Very Good Security', 'ats': 'lever', 'slug': 'verygoodsecurity', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Vesta', 'ats': 'ashby', 'slug': 'vesta', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Vitally', 'ats': 'ashby', 'slug': 'vitally', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Voldex', 'ats': 'ashby', 'slug': 'voldex', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Wayflyer', 'ats': 'ashby', 'slug': 'wayflyer', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Waymark', 'ats': 'greenhouse', 'slug': 'waymark', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Webflow', 'ats': 'greenhouse', 'slug': 'webflow', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Wellthy', 'ats': 'greenhouse', 'slug': 'wellthy', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Whatnot', 'ats': 'ashby', 'slug': 'whatnot', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Wingspan', 'ats': 'greenhouse', 'slug': 'wingspan', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Wonderschool', 'ats': 'greenhouse', 'slug': 'wonderschool', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Workboard', 'ats': 'greenhouse', 'slug': 'workboard', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'WorkOS', 'ats': 'ashby', 'slug': 'workos', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Wrapbook', 'ats': 'ashby', 'slug': 'wrapbook', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'xAI', 'ats': 'greenhouse', 'slug': 'xai', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Xendit', 'ats': 'greenhouse', 'slug': 'xendit', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Yotpo', 'ats': 'greenhouse', 'slug': 'yotpo', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Yubico', 'ats': 'greenhouse', 'slug': 'yubico', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Yuno', 'ats': 'lever', 'slug': 'yuno', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Zencoder', 'ats': 'greenhouse', 'slug': 'zencoder', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'ZeroMark', 'ats': 'ashby', 'slug': 'zeromark', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Zest AI', 'ats': 'greenhouse', 'slug': 'zestai', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Zopa', 'ats': 'lever', 'slug': 'zopa', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Zuma', 'ats': 'lever', 'slug': 'getzuma', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Zus Health', 'ats': 'lever', 'slug': 'zushealth', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Chainguard', 'ats': 'greenhouse', 'slug': 'chainguard', 'stage': 'Other', 'vertical': 'Security'},
    {'name': 'Apiiro', 'ats': 'greenhouse', 'slug': 'apiiro', 'stage': 'Growth', 'vertical': 'Security'},
    {'name': 'Profound', 'ats': 'ashby', 'slug': 'profound', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Shift Technology', 'ats': 'greenhouse', 'slug': 'shifttechnology', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Magic Eden', 'ats': 'ashby', 'slug': 'magiceden', 'stage': 'Growth', 'vertical': 'Fintech'},
    {'name': 'Moveworks', 'ats': 'greenhouse', 'slug': 'moveworks', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Snorkel AI', 'ats': 'greenhouse', 'slug': 'snorkelai', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Temporal Technologies', 'ats': 'greenhouse', 'slug': 'temporaltechnologies', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Semgrep', 'ats': 'ashby', 'slug': 'semgrep', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Tabs', 'ats': 'ashby', 'slug': 'tabs', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Corelight', 'ats': 'greenhouse', 'slug': 'corelight', 'stage': 'Series C Plus', 'vertical': 'Security'},
    {'name': 'Melio', 'ats': 'greenhouse', 'slug': 'melio', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'SonarSource', 'ats': 'lever', 'slug': 'sonarsource', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Inworld AI', 'ats': 'ashby', 'slug': 'inworld-ai', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'TRACTIAN', 'ats': 'lever', 'slug': 'tractian', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Nova Credit', 'ats': 'greenhouse', 'slug': 'novacredit', 'stage': 'Growth', 'vertical': 'Fintech'},
    {'name': 'Teya', 'ats': 'ashby', 'slug': 'teya', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Middesk', 'ats': 'ashby', 'slug': 'middesk', 'stage': 'Growth', 'vertical': 'Fintech'},
    {'name': 'Ethos Life', 'ats': 'greenhouse', 'slug': 'ethoslife', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Monzo', 'ats': 'greenhouse', 'slug': 'monzo', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Parloa', 'ats': 'greenhouse', 'slug': 'parloa', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Multiverse', 'ats': 'ashby', 'slug': 'multiverse', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Socure', 'ats': 'ashby', 'slug': 'socure', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Circle', 'ats': 'greenhouse', 'slug': 'circleso', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Aura', 'ats': 'greenhouse', 'slug': 'aura', 'stage': 'Other', 'vertical': 'Security'},
    {'name': 'SecurityScorecard', 'ats': 'greenhouse', 'slug': 'securityscorecard', 'stage': 'Growth', 'vertical': 'Security'},
    {'name': 'Rain', 'ats': 'ashby', 'slug': 'rain', 'stage': 'Growth', 'vertical': 'Fintech'},
    {'name': 'Cognite', 'ats': 'greenhouse', 'slug': 'cognite', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'baseten', 'ats': 'ashby', 'slug': 'baseten', 'stage': 'Growth', 'vertical': 'AI'},
    {'name': 'Lessen', 'ats': 'lever', 'slug': 'lessen', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Found', 'ats': 'ashby', 'slug': 'found', 'stage': 'Growth', 'vertical': 'Fintech'},
    {'name': 'Supabase', 'ats': 'ashby', 'slug': 'supabase', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Tailscale', 'ats': 'greenhouse', 'slug': 'tailscale', 'stage': 'Other', 'vertical': 'Security'},
    {'name': 'Fireblocks', 'ats': 'greenhouse', 'slug': 'fireblocks', 'stage': 'Unknown', 'vertical': 'Security'},
    {'name': 'Galileo Financial Technologies', 'ats': 'greenhouse', 'slug': 'galileofinancialtechnologies', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Radar', 'ats': 'ashby', 'slug': 'radar', 'stage': 'Other', 'vertical': 'Security'},
    {'name': 'Omnea', 'ats': 'ashby', 'slug': 'omnea', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'GoCardless', 'ats': 'greenhouse', 'slug': 'gocardless', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Dash0', 'ats': 'ashby', 'slug': 'dash0', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Acceldata', 'ats': 'lever', 'slug': 'acceldata', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'PhysicsX', 'ats': 'greenhouse', 'slug': 'physicsx', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Braintrust Data', 'ats': 'ashby', 'slug': 'braintrust', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Nooks', 'ats': 'ashby', 'slug': 'nooks', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Standard Bots', 'ats': 'ashby', 'slug': 'standardbots', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Menlo Security', 'ats': 'ashby', 'slug': 'menlosecurity', 'stage': 'Series C Plus', 'vertical': 'Security'},
    {'name': 'Obsidian Security', 'ats': 'greenhouse', 'slug': 'obsidiansecurity', 'stage': 'Growth', 'vertical': 'AI'},
    {'name': 'Exa', 'ats': 'ashby', 'slug': 'exa', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'AirOps', 'ats': 'ashby', 'slug': 'airops', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'AppZen', 'ats': 'lever', 'slug': 'appzen', 'stage': 'Growth', 'vertical': 'Fintech'},
    {'name': 'Tines', 'ats': 'greenhouse', 'slug': 'tines', 'stage': 'Other', 'vertical': 'Security'},
    {'name': 'Klaviyo', 'ats': 'greenhouse', 'slug': 'klaviyo', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Celonis', 'ats': 'greenhouse', 'slug': 'celonis', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Overjet', 'ats': 'ashby', 'slug': 'overjet', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Typeface', 'ats': 'greenhouse', 'slug': 'typeface', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Tacto', 'ats': 'ashby', 'slug': 'tacto', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Vapi', 'ats': 'ashby', 'slug': 'vapi', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Funding Circle', 'ats': 'ashby', 'slug': 'fundingcircle', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Sysdig', 'ats': 'lever', 'slug': 'sysdig', 'stage': 'Series C Plus', 'vertical': 'Security'},
    {'name': 'DriveWealth', 'ats': 'greenhouse', 'slug': 'drivewealth', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Yugabyte', 'ats': 'greenhouse', 'slug': 'yugabyte', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Imprint', 'ats': 'ashby', 'slug': 'imprint', 'stage': 'Unknown', 'vertical': 'Fintech'},
    {'name': 'Amperity', 'ats': 'greenhouse', 'slug': 'amperity', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Coast', 'ats': 'greenhouse', 'slug': 'coast', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Veriff', 'ats': 'greenhouse', 'slug': 'veriff', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Aspora', 'ats': 'ashby', 'slug': 'aspora', 'stage': 'Series A', 'vertical': 'Fintech'},
    {'name': 'Huntress', 'ats': 'greenhouse', 'slug': 'huntress', 'stage': 'Growth', 'vertical': 'Security'},
    {'name': 'commercetools', 'ats': 'greenhouse', 'slug': 'commercetools', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Tendo', 'ats': 'lever', 'slug': 'tendo', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Hometap', 'ats': 'greenhouse', 'slug': 'hometap', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Netskope', 'ats': 'greenhouse', 'slug': 'netskope', 'stage': 'Other', 'vertical': 'Security'},
    {'name': 'Insify', 'ats': 'lever', 'slug': 'insify', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Cadence Solutions', 'ats': 'greenhouse', 'slug': 'cadencesolutions', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Matillion', 'ats': 'lever', 'slug': 'matillion', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Granola', 'ats': 'ashby', 'slug': 'granola', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'CertiK', 'ats': 'lever', 'slug': 'certik', 'stage': 'Growth', 'vertical': 'Security'},
    {'name': 'Anrok', 'ats': 'ashby', 'slug': 'anrok', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Primer', 'ats': 'ashby', 'slug': 'primer', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Lemonade', 'ats': 'ashby', 'slug': 'lemonade', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Buildkite', 'ats': 'greenhouse', 'slug': 'buildkite', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Secureframe', 'ats': 'lever', 'slug': 'secureframe', 'stage': 'Growth', 'vertical': 'Security'},
    {'name': 'FullStory', 'ats': 'ashby', 'slug': 'fullstory', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Synthflow', 'ats': 'ashby', 'slug': 'synthflow', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Qualtrics', 'ats': 'greenhouse', 'slug': 'qualtrics', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Dropbox', 'ats': 'greenhouse', 'slug': 'dropbox', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Pilot', 'ats': 'greenhouse', 'slug': 'pilothq', 'stage': 'Growth', 'vertical': 'Fintech'},
    {'name': 'Array', 'ats': 'greenhouse', 'slug': 'array', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Awardco', 'ats': 'greenhouse', 'slug': 'awardco', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Eudia', 'ats': 'greenhouse', 'slug': 'eudia', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Builder.io', 'ats': 'greenhouse', 'slug': 'builder', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Sonatype', 'ats': 'lever', 'slug': 'sonatype', 'stage': 'Other', 'vertical': 'Security'},
    {'name': 'Vestwell', 'ats': 'greenhouse', 'slug': 'vestwell', 'stage': 'Growth', 'vertical': 'Fintech'},
    {'name': 'Filigran', 'ats': 'ashby', 'slug': 'filigran', 'stage': 'Other', 'vertical': 'Security'},
    {'name': 'Ping Identity', 'ats': 'greenhouse', 'slug': 'pingidentity', 'stage': 'Other', 'vertical': 'Security'},
    {'name': 'Singular', 'ats': 'ashby', 'slug': 'singular', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Dremio', 'ats': 'greenhouse', 'slug': 'dremio', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Offchain Labs', 'ats': 'lever', 'slug': 'offchainlabs', 'stage': 'Unknown', 'vertical': 'Fintech'},
    {'name': 'Notable', 'ats': 'ashby', 'slug': 'notable', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Jellyfish', 'ats': 'ashby', 'slug': 'jellyfish', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Traba', 'ats': 'ashby', 'slug': 'traba', 'stage': 'Other', 'vertical': 'Marketplace'},
    {'name': 'Common Room', 'ats': 'ashby', 'slug': 'commonroom', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Wallapop', 'ats': 'greenhouse', 'slug': 'wallapop', 'stage': 'Other', 'vertical': 'Marketplace'},
    {'name': 'Anomali', 'ats': 'lever', 'slug': 'anomali', 'stage': 'Series C Plus', 'vertical': 'Security'},
    {'name': 'Oligo Security', 'ats': 'ashby', 'slug': 'oligo', 'stage': 'Growth', 'vertical': 'Security'},
    {'name': 'New Relic', 'ats': 'greenhouse', 'slug': 'newrelic', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Domino Data Lab', 'ats': 'greenhouse', 'slug': 'dominodatalab', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Brigit', 'ats': 'ashby', 'slug': 'brigit', 'stage': 'Series A', 'vertical': 'Fintech'},
    {'name': 'Checkr', 'ats': 'greenhouse', 'slug': 'checkr', 'stage': 'Undisclosed', 'vertical': 'AI'},
    {'name': 'Redpanda Data', 'ats': 'greenhouse', 'slug': 'redpandadata', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Finix', 'ats': 'lever', 'slug': 'finix', 'stage': 'Growth', 'vertical': 'Fintech'},
    {'name': 'Postscript', 'ats': 'greenhouse', 'slug': 'postscript', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'First Street Foundation', 'ats': 'ashby', 'slug': 'firststreet', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Goodstack', 'ats': 'ashby', 'slug': 'goodstack', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'eko', 'ats': 'greenhouse', 'slug': 'eko', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Enable', 'ats': 'lever', 'slug': 'enable', 'stage': 'Growth', 'vertical': 'Fintech'},
    {'name': 'Material Bank', 'ats': 'greenhouse', 'slug': 'materialbank', 'stage': 'Other', 'vertical': 'Marketplace'},
    {'name': 'Clari', 'ats': 'lever', 'slug': 'clari', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Checkly', 'ats': 'ashby', 'slug': 'checkly', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Aquant', 'ats': 'ashby', 'slug': 'aquant', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Knoetic', 'ats': 'ashby', 'slug': 'knoetic', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Logz.io', 'ats': 'lever', 'slug': 'logz', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Lightrun', 'ats': 'greenhouse', 'slug': 'lightrun', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Nexus', 'ats': 'greenhouse', 'slug': 'nexus', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Dovetail', 'ats': 'ashby', 'slug': 'dovetail', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Resilience', 'ats': 'greenhouse', 'slug': 'resilience', 'stage': 'Series C Plus', 'vertical': 'Security'},
    {'name': 'Cobot', 'ats': 'ashby', 'slug': 'cobot', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Lightfield', 'ats': 'ashby', 'slug': 'lightfield', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Genesis Global', 'ats': 'ashby', 'slug': 'genesis-ai', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'General Catalyst', 'ats': 'greenhouse', 'slug': 'generalcatalyst', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Nuna', 'ats': 'ashby', 'slug': 'nuna', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Fintual', 'ats': 'lever', 'slug': 'fintual', 'stage': 'Unknown', 'vertical': 'Fintech'},
    {'name': 'Sora Schools', 'ats': 'lever', 'slug': 'soraschools', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Bugcrowd', 'ats': 'greenhouse', 'slug': 'bugcrowd', 'stage': 'Other', 'vertical': 'Security'},
    {'name': 'Synctera', 'ats': 'ashby', 'slug': 'synctera', 'stage': 'Unknown', 'vertical': 'Fintech'},
    {'name': 'Wisetack', 'ats': 'greenhouse', 'slug': 'wisetack', 'stage': 'Growth', 'vertical': 'Fintech'},
    {'name': 'Pine', 'ats': 'greenhouse', 'slug': 'pine', 'stage': 'Series A', 'vertical': 'Fintech'},
    {'name': 'Magical', 'ats': 'ashby', 'slug': 'magical', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'SafeBreach', 'ats': 'greenhouse', 'slug': 'safebreach', 'stage': 'Growth', 'vertical': 'Security'},
    {'name': 'intenseye', 'ats': 'lever', 'slug': 'intenseye', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'The Predictive Index', 'ats': 'greenhouse', 'slug': 'predictiveindex', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Atrato', 'ats': 'ashby', 'slug': 'atrato', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Materialize', 'ats': 'greenhouse', 'slug': 'materialize', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Orum', 'ats': 'ashby', 'slug': 'orum', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Mercor', 'ats': 'ashby', 'slug': 'mercor', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'CRED', 'ats': 'lever', 'slug': 'cred', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Chalk', 'ats': 'ashby', 'slug': 'chalk', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'DualEntry', 'ats': 'ashby', 'slug': 'dualentry', 'stage': 'Series A', 'vertical': 'Fintech'},
    {'name': 'Roofstock', 'ats': 'greenhouse', 'slug': 'roofstock', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'nimble-robotics', 'ats': 'greenhouse', 'slug': 'nimblerobotics', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Process Street', 'ats': 'greenhouse', 'slug': 'processstreet', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Causal', 'ats': 'ashby', 'slug': 'causal', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Serval', 'ats': 'ashby', 'slug': 'serval', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Together AI', 'ats': 'greenhouse', 'slug': 'togetherai', 'stage': 'Unknown', 'vertical': 'AI'},
    {'name': 'Campfire', 'ats': 'ashby', 'slug': 'campfire', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Higgsfield AI', 'ats': 'ashby', 'slug': 'higgsfieldai', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Twenty', 'ats': 'ashby', 'slug': 'twenty', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Pave Bank', 'ats': 'ashby', 'slug': 'pavebank', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Culture AMP', 'ats': 'greenhouse', 'slug': 'cultureamp', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Netic', 'ats': 'ashby', 'slug': 'netic', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Pallet', 'ats': 'greenhouse', 'slug': 'pallet', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Wordsmith AI', 'ats': 'ashby', 'slug': 'wordsmith', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Layer Health', 'ats': 'greenhouse', 'slug': 'layerhealth', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Enter', 'ats': 'ashby', 'slug': 'enter-ai', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Finch', 'ats': 'ashby', 'slug': 'finch', 'stage': 'Series A', 'vertical': 'AI'},
    {'name': 'Meter', 'ats': 'ashby', 'slug': 'meter', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Re:Build Manufacturing', 'ats': 'greenhouse', 'slug': 'rebuildmanufacturing', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Cogent Security', 'ats': 'ashby', 'slug': 'cogent-security', 'stage': 'Series A', 'vertical': 'Security'},
    {'name': 'Ironclad', 'ats': 'ashby', 'slug': 'ironcladhq', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Vori', 'ats': 'ashby', 'slug': 'vori', 'stage': 'Series A', 'vertical': 'Marketplace'},
    {'name': 'Neko Health', 'ats': 'ashby', 'slug': 'neko-health', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'LlamaIndex', 'ats': 'ashby', 'slug': 'llamaindex', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Prodigal', 'ats': 'greenhouse', 'slug': 'prodigal', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Langfuse', 'ats': 'ashby', 'slug': 'langfuse', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Browserbase', 'ats': 'ashby', 'slug': 'browserbase', 'stage': 'Series A', 'vertical': 'AI'},
    {'name': 'lemon.markets', 'ats': 'ashby', 'slug': 'lemon-markets', 'stage': 'Unknown', 'vertical': 'Fintech'},
    {'name': 'Luminai', 'ats': 'ashby', 'slug': 'luminai', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Orb', 'ats': 'ashby', 'slug': 'orb', 'stage': 'Growth', 'vertical': 'Fintech'},
    {'name': 'Flow Engineering', 'ats': 'ashby', 'slug': 'flowengineering', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'PermitFlow', 'ats': 'ashby', 'slug': 'permitflow', 'stage': 'Series B', 'vertical': 'SaaS'},
    {'name': 'Modus', 'ats': 'ashby', 'slug': 'modus', 'stage': 'Unknown', 'vertical': 'Fintech'},
    {'name': 'InStride Health', 'ats': 'greenhouse', 'slug': 'instridehealth', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Ledgy', 'ats': 'greenhouse', 'slug': 'ledgy', 'stage': 'Series A', 'vertical': 'Fintech'},
    {'name': 'Watershed', 'ats': 'ashby', 'slug': 'watershed', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'RobCo', 'ats': 'ashby', 'slug': 'robco', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Opal', 'ats': 'ashby', 'slug': 'opal', 'stage': 'Growth', 'vertical': 'Security'},
    {'name': 'Radiant Security', 'ats': 'greenhouse', 'slug': 'radiantsecurity', 'stage': 'Series A', 'vertical': 'Security'},
    {'name': 'Fin', 'ats': 'ashby', 'slug': 'fin', 'stage': 'Series A', 'vertical': 'Fintech'},
    {'name': 'Pacific Fusion', 'ats': 'greenhouse', 'slug': 'pacificfusion', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Fireworks AI', 'ats': 'greenhouse', 'slug': 'fireworksai', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Prelude', 'ats': 'ashby', 'slug': 'prelude', 'stage': 'Unknown', 'vertical': 'Security'},
    {'name': 'Authzed', 'ats': 'ashby', 'slug': 'authzed', 'stage': 'Other', 'vertical': 'Security'},
    {'name': 'Hook', 'ats': 'ashby', 'slug': 'hook', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Cinder', 'ats': 'ashby', 'slug': 'cinder', 'stage': 'Other', 'vertical': 'Security'},
    {'name': 'FalconX', 'ats': 'greenhouse', 'slug': 'falconx', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Bedrock Security', 'ats': 'ashby', 'slug': 'bedrock', 'stage': 'Series A', 'vertical': 'Security'},
    {'name': 'Statsig', 'ats': 'ashby', 'slug': 'statsig', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Oso', 'ats': 'ashby', 'slug': 'oso', 'stage': 'Series A', 'vertical': 'Security'},
    {'name': 'Arcade Software', 'ats': 'ashby', 'slug': 'arcade', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Clarium', 'ats': 'ashby', 'slug': 'clarium', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Cortex', 'ats': 'greenhouse', 'slug': 'cortex', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Bretton AI', 'ats': 'ashby', 'slug': 'brettonai', 'stage': 'Growth', 'vertical': 'Fintech'},
    {'name': 'LightSource', 'ats': 'ashby', 'slug': 'lightsource', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Enterpret', 'ats': 'greenhouse', 'slug': 'enterpret', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Dexterity', 'ats': 'lever', 'slug': 'dexterity', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'WireScreen', 'ats': 'ashby', 'slug': 'wirescreen', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Deepnote', 'ats': 'ashby', 'slug': 'deepnote', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Eon.io', 'ats': 'greenhouse', 'slug': 'eonio', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Ladder', 'ats': 'ashby', 'slug': 'ladder', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Herald', 'ats': 'greenhouse', 'slug': 'heraldapi', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Lightdash', 'ats': 'ashby', 'slug': 'lightdash', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'unitQ', 'ats': 'lever', 'slug': 'unitq', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Atomic', 'ats': 'ashby', 'slug': 'atomic', 'stage': 'Unknown', 'vertical': 'Fintech'},
    {'name': 'Ranger', 'ats': 'lever', 'slug': 'ranger', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Warp', 'ats': 'ashby', 'slug': 'warp', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Casap', 'ats': 'ashby', 'slug': 'casap', 'stage': 'Series A', 'vertical': 'Fintech'},
    {'name': 'Evervault', 'ats': 'ashby', 'slug': 'evervault', 'stage': 'Series A', 'vertical': 'Security'},
    {'name': 'Thunkable', 'ats': 'lever', 'slug': 'thunkable', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Multiply', 'ats': 'ashby', 'slug': 'multiply', 'stage': 'Series A', 'vertical': 'Fintech'},
    {'name': 'AudioMob', 'ats': 'greenhouse', 'slug': 'audiomob', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Snapdocs', 'ats': 'ashby', 'slug': 'snapdocs', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Doppler', 'ats': 'ashby', 'slug': 'doppler', 'stage': 'Series A', 'vertical': 'Security'},
    {'name': 'Symbolica AI', 'ats': 'ashby', 'slug': 'symbolica-ai', 'stage': 'Other', 'vertical': 'AI'},
    {'name': 'Cleo', 'ats': 'greenhouse', 'slug': 'cleo', 'stage': 'Growth', 'vertical': 'Marketplace'},
    {'name': 'CookUnity', 'ats': 'greenhouse', 'slug': 'cookunity', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Graphcore', 'ats': 'greenhouse', 'slug': 'graphcore', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Finni Health', 'ats': 'ashby', 'slug': 'finni-health', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Macroscope', 'ats': 'ashby', 'slug': 'macroscope', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Alif Semiconductor', 'ats': 'lever', 'slug': 'alifsemi', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'SonderMind', 'ats': 'ashby', 'slug': 'sondermind', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Cartesia', 'ats': 'ashby', 'slug': 'cartesia', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Helion', 'ats': 'ashby', 'slug': 'helion', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'ICEYE', 'ats': 'ashby', 'slug': 'iceye', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Contentful', 'ats': 'greenhouse', 'slug': 'contentful', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Mainspring Energy', 'ats': 'lever', 'slug': 'mainspringenergy', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Félix', 'ats': 'greenhouse', 'slug': 'flix', 'stage': 'Series B', 'vertical': 'SaaS'},
    {'name': 'Tonkean', 'ats': 'lever', 'slug': 'tonkean', 'stage': 'Series B', 'vertical': 'SaaS'},
    {'name': 'Zerion', 'ats': 'lever', 'slug': 'zerion', 'stage': 'Growth', 'vertical': 'Fintech'},
    {'name': 'Beam', 'ats': 'ashby', 'slug': 'beam', 'stage': 'Other', 'vertical': 'Fintech'},
    {'name': 'Anagram', 'ats': 'ashby', 'slug': 'anagram', 'stage': 'Other', 'vertical': 'Security'},
    {'name': 'Brainly', 'ats': 'ashby', 'slug': 'brainly', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'StackBlitz', 'ats': 'greenhouse', 'slug': 'stackblitz', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Noetica AI', 'ats': 'ashby', 'slug': 'noetica', 'stage': 'Unknown', 'vertical': 'Fintech'},
    {'name': 'Andesite', 'ats': 'greenhouse', 'slug': 'andesite', 'stage': 'Other', 'vertical': 'Security'},
    {'name': 'SENTRY', 'ats': 'ashby', 'slug': 'sentry', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Hive', 'ats': 'greenhouse', 'slug': 'hive', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Clara', 'ats': 'greenhouse', 'slug': 'clara', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Zūm', 'ats': 'lever', 'slug': 'ridezum', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Kodiak Robotics', 'ats': 'greenhouse', 'slug': 'kodiak', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Lottie', 'ats': 'ashby', 'slug': 'lottie', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Algolia', 'ats': 'greenhouse', 'slug': 'algolia', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Daybreak Health', 'ats': 'greenhouse', 'slug': 'daybreakhealth', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Govini', 'ats': 'greenhouse', 'slug': 'govini', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Fictiv', 'ats': 'greenhouse', 'slug': 'fictiv', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Ro', 'ats': 'lever', 'slug': 'ro', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Cameo', 'ats': 'greenhouse', 'slug': 'cameo', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Sumo Logic', 'ats': 'greenhouse', 'slug': 'sumologic', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Speak', 'ats': 'ashby', 'slug': 'speak', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Misfits Market', 'ats': 'greenhouse', 'slug': 'misfitsmarket', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Mark43', 'ats': 'greenhouse', 'slug': 'mark43', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Reflection AI', 'ats': 'ashby', 'slug': 'reflectionai', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Equip', 'ats': 'ashby', 'slug': 'equip', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Iru', 'ats': 'lever', 'slug': 'iru', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Mindtickle', 'ats': 'lever', 'slug': 'mindtickle', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Proxima Fusion', 'ats': 'ashby', 'slug': 'proxima-fusion', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Thinking Machines Lab', 'ats': 'greenhouse', 'slug': 'thinkingmachines', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'G2', 'ats': 'ashby', 'slug': 'g2', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Sarvam AI', 'ats': 'ashby', 'slug': 'sarvam', 'stage': 'Unknown', 'vertical': 'AI'},
    {'name': 'Veza', 'ats': 'greenhouse', 'slug': 'veza', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Pylon', 'ats': 'ashby', 'slug': 'pylon', 'stage': 'Series B', 'vertical': 'SaaS'},
    {'name': 'GOAT Group', 'ats': 'greenhouse', 'slug': 'goatgroup', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'H Company', 'ats': 'ashby', 'slug': 'hcompany', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Scale AI', 'ats': 'greenhouse', 'slug': 'scaleai', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Gopuff', 'ats': 'lever', 'slug': 'gopuff', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Campus', 'ats': 'ashby', 'slug': 'campus', 'stage': 'Series B', 'vertical': 'SaaS'},
    {'name': 'Assort Health', 'ats': 'ashby', 'slug': 'assorthealth', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Newsela', 'ats': 'greenhouse', 'slug': 'newsela', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Distyl AI', 'ats': 'ashby', 'slug': 'distyl', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Weee!', 'ats': 'greenhouse', 'slug': 'weee', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Ambience Healthcare', 'ats': 'ashby', 'slug': 'ambiencehealthcare', 'stage': 'Growth', 'vertical': 'AI'},
    {'name': 'Strava', 'ats': 'ashby', 'slug': 'strava', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Merge', 'ats': 'greenhouse', 'slug': 'merge', 'stage': 'Series B', 'vertical': 'SaaS'},
    {'name': 'NanoNets', 'ats': 'greenhouse', 'slug': 'nanonets', 'stage': 'Series B', 'vertical': 'SaaS'},
    {'name': 'Pair Team', 'ats': 'greenhouse', 'slug': 'pairteam', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Nas Company', 'ats': 'greenhouse', 'slug': 'nascompany', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Crosby', 'ats': 'ashby', 'slug': 'crosby', 'stage': 'Growth', 'vertical': 'AI'},
    {'name': 'Zefir', 'ats': 'ashby', 'slug': 'zefir', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Render', 'ats': 'ashby', 'slug': 'render', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'MinIO', 'ats': 'greenhouse', 'slug': 'minio', 'stage': 'Series B', 'vertical': 'SaaS'},
    {'name': 'ClassDojo', 'ats': 'ashby', 'slug': 'classdojo', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Thatch', 'ats': 'greenhouse', 'slug': 'thatch', 'stage': 'Series B', 'vertical': 'SaaS'},
    {'name': 'Truecaller', 'ats': 'greenhouse', 'slug': 'truecaller', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Carbon', 'ats': 'greenhouse', 'slug': 'carbon', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'AtoB', 'ats': 'ashby', 'slug': 'atob', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'August Health', 'ats': 'ashby', 'slug': 'august-health', 'stage': 'Series B', 'vertical': 'SaaS'},
    {'name': 'Invoca', 'ats': 'greenhouse', 'slug': 'invoca', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'goop,com', 'ats': 'greenhouse', 'slug': 'goop', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Stability AI', 'ats': 'greenhouse', 'slug': 'stabilityai', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Unit', 'ats': 'ashby', 'slug': 'unit', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Modern Health', 'ats': 'greenhouse', 'slug': 'modernhealth', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Cobalt Robotics', 'ats': 'lever', 'slug': 'cobaltrobotics', 'stage': 'Unknown', 'vertical': 'AI'},
    {'name': 'Tourlane', 'ats': 'ashby', 'slug': 'tourlane', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Salt Security', 'ats': 'greenhouse', 'slug': 'saltsecurity', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Infinitus Systems', 'ats': 'ashby', 'slug': 'infinitus', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Hungryroot', 'ats': 'greenhouse', 'slug': 'hungryroot', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Fiddler AI', 'ats': 'ashby', 'slug': 'fiddler-ai', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Monarch Money', 'ats': 'ashby', 'slug': 'monarchmoney', 'stage': 'Series B', 'vertical': 'SaaS'},
    {'name': 'Wheel', 'ats': 'ashby', 'slug': 'wheel', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'UiPath', 'ats': 'ashby', 'slug': 'uipath', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Future', 'ats': 'greenhouse', 'slug': 'future', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Cloaked', 'ats': 'ashby', 'slug': 'cloaked', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'AMP Sortation', 'ats': 'greenhouse', 'slug': 'ampsortation', 'stage': 'Growth', 'vertical': 'AI'},
    {'name': 'Airbyte', 'ats': 'ashby', 'slug': 'airbyte', 'stage': 'Series B', 'vertical': 'SaaS'},
    {'name': 'Dolls Kill', 'ats': 'lever', 'slug': 'dollskill', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Freed', 'ats': 'ashby', 'slug': 'freed', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Contrast Security', 'ats': 'ashby', 'slug': 'contrast-security', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Plume', 'ats': 'greenhouse', 'slug': 'plume', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'AssemblyAI', 'ats': 'greenhouse', 'slug': 'assemblyai', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Zola', 'ats': 'greenhouse', 'slug': 'zola', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'VEED.IO', 'ats': 'greenhouse', 'slug': 'veedio', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Charm Industrial', 'ats': 'lever', 'slug': 'charmindustrial', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Vivun', 'ats': 'ashby', 'slug': 'vivun', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'TrustArc', 'ats': 'lever', 'slug': 'trustarc', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Aven', 'ats': 'ashby', 'slug': 'aven', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'BlaBlaCar', 'ats': 'lever', 'slug': 'blablacar', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Neon', 'ats': 'ashby', 'slug': 'neon', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'BetterCloud', 'ats': 'ashby', 'slug': 'bettercloud', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Fizz', 'ats': 'ashby', 'slug': 'fizz', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Public.com', 'ats': 'greenhouse', 'slug': 'public', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Homeward', 'ats': 'greenhouse', 'slug': 'homeward', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Vim', 'ats': 'greenhouse', 'slug': 'vim', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'ReadMe', 'ats': 'ashby', 'slug': 'readme', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Traversal', 'ats': 'ashby', 'slug': 'traversal', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Gyde', 'ats': 'greenhouse', 'slug': 'gyde', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'MyFitnessPal', 'ats': 'greenhouse', 'slug': 'myfitnesspal', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Beautiful.AI', 'ats': 'greenhouse', 'slug': 'beautifulai', 'stage': 'Series B', 'vertical': 'SaaS'},
    {'name': 'Lila Sciences', 'ats': 'greenhouse', 'slug': 'lilasciences', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Mosaic.tech', 'ats': 'ashby', 'slug': 'mosaic', 'stage': 'Series C Plus', 'vertical': 'SaaS'},
    {'name': 'Good Eggs', 'ats': 'lever', 'slug': 'goodeggs', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'Better Health Supplies', 'ats': 'ashby', 'slug': 'joinbetter', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'SingleStore', 'ats': 'greenhouse', 'slug': 'singlestore', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Beacon Software', 'ats': 'greenhouse', 'slug': 'beaconsoftware', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Doctronic', 'ats': 'ashby', 'slug': 'doctronic', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Listen Labs', 'ats': 'ashby', 'slug': 'listenlabs', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Arena', 'ats': 'ashby', 'slug': 'arena', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Goodfire', 'ats': 'greenhouse', 'slug': 'goodfire', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Reflect Orbital', 'ats': 'ashby', 'slug': 'reflect-orbital', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Composio', 'ats': 'ashby', 'slug': 'composio', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Truv', 'ats': 'lever', 'slug': 'truv', 'stage': 'Series A', 'vertical': 'Fintech'},
    {'name': 'Mithril', 'ats': 'greenhouse', 'slug': 'mithril', 'stage': 'Unknown', 'vertical': 'AI'},
    {'name': 'Delphi', 'ats': 'ashby', 'slug': 'delphi', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Quantum Circuits', 'ats': 'lever', 'slug': 'quantumcircuits', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Anterior', 'ats': 'ashby', 'slug': 'anterior', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'shapes inc', 'ats': 'ashby', 'slug': 'shapes', 'stage': 'Unknown', 'vertical': 'SaaS'},
    {'name': 'FERMAT', 'ats': 'greenhouse', 'slug': 'fermat', 'stage': 'Growth', 'vertical': 'Marketplace'},
    {'name': 'Fathom', 'ats': 'ashby', 'slug': 'fathom', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'Summer Health', 'ats': 'ashby', 'slug': 'summerhealth', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Virtue AI', 'ats': 'ashby', 'slug': 'virtue-ai', 'stage': 'Series A', 'vertical': 'SaaS'},
    {'name': 'Summer​', 'ats': 'greenhouse', 'slug': 'summer', 'stage': 'Other', 'vertical': 'SaaS'},
    {'name': 'Truework', 'ats': 'greenhouse', 'slug': 'truework', 'stage': 'Growth', 'vertical': 'SaaS'},
    {'name': 'TollBit', 'ats': 'greenhouse', 'slug': 'tollbit', 'stage': 'Unknown', 'vertical': 'SaaS'},
]

def load_companies_from_db():
    """Load Scout companies from SQLite, falling back to COMPANIES on error."""
    source_mode = os.environ.get('PP_JOBAPP_COMPANY_SOURCE', 'auto').lower()
    if source_mode == 'legacy':
        return COMPANIES, 'legacy'
    if source_mode not in ('auto', 'db'):
        print("WARN: Unknown PP_JOBAPP_COMPANY_SOURCE=" + source_mode + "; using auto")
    if not os.path.exists(DB_PATH):
        if source_mode == 'db':
            print("WARN: SQLite DB not found at " + DB_PATH + "; using legacy COMPANIES")
        return COMPANIES, 'legacy'
    try:
        sys.path.insert(0, SCRIPTS)
        import storage
        conn = storage.connect(DB_PATH)
        try:
            companies = storage.load_scout_companies(conn)
        finally:
            conn.close()
        if not companies:
            print("WARN: SQLite company load returned 0 rows; using legacy COMPANIES")
            return COMPANIES, 'legacy'
        return companies, 'sqlite'
    except Exception as e:
        print("WARN: SQLite company load failed: " + str(e)[:160] + "; using legacy COMPANIES")
        return COMPANIES, 'legacy'

# ============================================================
# Helpers
# ============================================================

def fetch_url(url):
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None

def parse_date(raw):
    if not raw:
        return ''
    try:
        return raw[:10]
    except Exception:
        return str(raw)[:10]

def days_ago(date_str):
    if not date_str:
        return None
    try:
        d = datetime.date.fromisoformat(date_str[:10])
        return (datetime.date.today() - d).days
    except Exception:
        return None

def _strip_html(s):
    if not s:
        return ''
    import re as _re, html as _html
    s = str(s)
    for _ in range(3):
        prev = s
        s = _html.unescape(s)
        if s == prev:
            break
    s = _re.sub(r'<[^>]+>', ' ', s)
    s = _re.sub(r'\s+', ' ', s).strip()
    return s

def _extract_jd(j, source, cap=None):
    cap = cap or JD_CAP
    if source == 'ashby':
        text = j.get('descriptionPlain') or _strip_html(j.get('descriptionHtml', ''))
    elif source == 'greenhouse':
        text = _strip_html(j.get('content', ''))
    elif source == 'lever':
        parts = [j.get('descriptionPlain') or _strip_html(j.get('description', ''))]
        for lst in (j.get('lists') or []):
            heading = lst.get('text', '')
            body = _strip_html(lst.get('content', ''))
            if heading or body:
                parts.append((heading + ': ' if heading else '') + body)
        extra = j.get('additionalPlain') or _strip_html(j.get('additional', ''))
        if extra:
            parts.append(extra)
        text = '\n'.join(p for p in parts if p)
    else:
        text = ''
    return text[:cap] if text else ''

def evaluate_role(title, jd_text):
    """
    Returns (match: bool, reason: str, matched_keyword: str)
    Reasons: title_match | jd_fallback | rejected_negative | rejected_no_match
    Negative title keywords ALWAYS reject, even if JD has fallback signals.
    """
    t = (title or '').lower()
    jd = (jd_text or '').lower()

    for neg in TITLE_NEGATIVE:
        if neg in t:
            return False, 'rejected_negative', neg

    for pos in TITLE_POSITIVE:
        if pos in t:
            return True, 'title_match', pos

    if JD_FALLBACK_ENABLED and jd:
        for phrase in JD_FALLBACK_PHRASES:
            if phrase in jd:
                return True, 'jd_fallback', phrase

    return False, 'rejected_no_match', ''

# ============================================================
# Per-platform fetchers
# ============================================================

def fetch_ashby(company):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company['slug']}?includeCompensation=true"
    data = fetch_url(url)
    if not data:
        return [], 0
    all_jobs = data.get('jobs', [])
    matches = []
    for j in all_jobs:
        title = j.get('title', '')
        jd_text = _extract_jd(j, 'ashby')
        is_match, reason, kw = evaluate_role(title, jd_text)
        if not is_match:
            continue
        location = j.get('location', '') or ''
        if isinstance(location, dict):
            location = location.get('name', '')
        posted = parse_date(j.get('publishedAt', ''))
        matches.append({
            'company_name': company['name'],
            'role_title': title,
            'apply_url': j.get('applyUrl') or j.get('jobUrl', ''),
            'job_url': j.get('jobUrl', ''),
            'source': 'ashby',
            'date_found': str(datetime.date.today()),
            'posted_date': posted,
            'days_ago': days_ago(posted),
            'location_raw': location,
            'remote_ok': j.get('isRemote', False),
            'company_stage': company.get('stage', 'Unknown'),
            'industry_vertical': company.get('vertical', 'Unknown'),
            'ai_native': company.get('vertical') == 'AI',
            'compensation': j.get('compensation', {}).get('compensationTierSummary', '') if j.get('compensation') else '',
            'jd_text': jd_text,
            'match_reason': reason,
            'matched_keyword': kw,
        })
    return matches, len(all_jobs)

def fetch_greenhouse(company):
    # FIX: was api.greenhouse.io (wrong host), now boards-api.greenhouse.io (correct public API)
    url = f"https://boards-api.greenhouse.io/v1/boards/{company['slug']}/jobs?content=true"
    data = fetch_url(url)
    if not data:
        return [], 0
    all_jobs = data.get('jobs', [])
    matches = []
    for j in all_jobs:
        title = j.get('title', '')
        jd_text = _extract_jd(j, 'greenhouse')
        is_match, reason, kw = evaluate_role(title, jd_text)
        if not is_match:
            continue
        location = j.get('location', {})
        if isinstance(location, dict):
            location = location.get('name', '')
        posted = parse_date(j.get('updated_at', '') or j.get('first_published', ''))
        matches.append({
            'company_name': company['name'],
            'role_title': title,
            'apply_url': j.get('absolute_url', ''),
            'job_url': j.get('absolute_url', ''),
            'source': 'greenhouse',
            'date_found': str(datetime.date.today()),
            'posted_date': posted,
            'days_ago': days_ago(posted),
            'location_raw': location,
            'remote_ok': 'remote' in location.lower() if location else False,
            'company_stage': company.get('stage', 'Unknown'),
            'industry_vertical': company.get('vertical', 'Unknown'),
            'ai_native': company.get('vertical') == 'AI',
            'compensation': '',
            'jd_text': jd_text,
            'match_reason': reason,
            'matched_keyword': kw,
        })
    return matches, len(all_jobs)

def fetch_lever(company):
    url = f"https://api.lever.co/v0/postings/{company['slug']}"
    data = fetch_url(url)
    if not data or not isinstance(data, list):
        return [], 0
    matches = []
    for j in data:
        title = j.get('text', '')
        jd_text = _extract_jd(j, 'lever')
        is_match, reason, kw = evaluate_role(title, jd_text)
        if not is_match:
            continue
        cats = j.get('categories', {})
        location = cats.get('location', '') or ''
        raw_ts = j.get('createdAt', 0)
        posted = ''
        if raw_ts:
            try:
                posted = str(datetime.date.fromtimestamp(raw_ts / 1000))
            except Exception:
                posted = ''
        matches.append({
            'company_name': company['name'],
            'role_title': title,
            'apply_url': j.get('applyUrl', j.get('hostedUrl', '')),
            'job_url': j.get('hostedUrl', ''),
            'source': 'lever',
            'date_found': str(datetime.date.today()),
            'posted_date': posted,
            'days_ago': days_ago(posted),
            'location_raw': location,
            'remote_ok': 'remote' in location.lower() if location else False,
            'company_stage': company.get('stage', 'Unknown'),
            'industry_vertical': company.get('vertical', 'Unknown'),
            'ai_native': company.get('vertical') == 'AI',
            'compensation': '',
            'jd_text': jd_text,
            'match_reason': reason,
            'matched_keyword': kw,
        })
    return matches, len(data)


def discover_phase(conn, limit=None, max_age_days=30):
    """For every active company missing an ATS endpoint (or with a stale
    not_found endpoint), run storage.detect_ats() and record the result.

    Hits become status='active', misses become status='not_found' with a
    placeholder slug (so the UNIQUE(provider, slug) constraint is satisfied).
    Dead URLs (DNS NXDOMAIN) become provider='broken'.

    Args:
        conn: open sqlite3.Connection
        limit: max companies to process this run (None = all eligible)
        max_age_days: re-try not_found companies after this many days

    Returns:
        {"tried", "hits", "misses", "dead_urls", "errors", "by_provider"}
    """
    import time as _time
    import traceback as _tb
    sys.path.insert(0, SCRIPTS)
    import storage  # noqa: E402

    age_modifier = f"-{int(max_age_days)} days"
    rows = conn.execute(
        """
        SELECT c.id, c.canonical_name, c.website_url
        FROM companies c
        WHERE c.active = 1
          AND NOT EXISTS (
              SELECT 1 FROM ats_endpoints e
              WHERE e.company_id = c.id
                AND e.status IN ('active', 'skipped')
          )
          AND NOT EXISTS (
              SELECT 1 FROM ats_endpoints e
              WHERE e.company_id = c.id
                AND e.status = 'not_found'
                AND e.last_checked_at IS NOT NULL
                AND e.last_checked_at > datetime('now', :age)
          )
        ORDER BY c.id
        """,
        {"age": age_modifier},
    ).fetchall()
    if limit is not None:
        rows = rows[:limit]

    stats = {
        "tried": 0, "hits": 0, "misses": 0, "dead_urls": 0, "errors": 0,
        "by_provider": {},
    }
    log_path = WORKSPACE + "/discover_phase.log"
    os.makedirs(WORKSPACE, exist_ok=True)
    log_fh = open(log_path, "a")
    try:
        log_fh.write(
            "\n--- discover_phase start " + datetime.datetime.now().isoformat()
            + " (n=" + str(len(rows)) + ", max_age_days=" + str(max_age_days)
            + ", limit=" + str(limit) + ") ---\n"
        )
        log_fh.flush()
        for i, row in enumerate(rows, 1):
            cid = int(row["id"])
            name = row["canonical_name"]
            url = row["website_url"]
            stats["tried"] += 1
            try:
                result = storage.detect_ats(name, url)
            except Exception as e:
                log_fh.write(
                    "[" + str(cid) + " " + repr(name) + "] EXCEPTION: "
                    + type(e).__name__ + ": " + str(e) + "\n" + _tb.format_exc() + "\n"
                )
                log_fh.flush()
                stats["errors"] += 1
                _time.sleep(0.4)
                continue

            try:
                if result and result.get("provider"):
                    provider = result["provider"]
                    slug = result["slug"]
                    total = result.get("total_jobs")
                    storage.upsert_ats_endpoint(
                        conn, cid,
                        provider=provider, slug=slug,
                        ats_url=storage.ats_url(provider, slug),
                        status="active",
                        open_jobs_actual=total if isinstance(total, int) else None,
                        raw_metadata={"found_via": result.get("found_via", "")},
                    )
                    conn.commit()
                    stats["hits"] += 1
                    stats["by_provider"][provider] = stats["by_provider"].get(provider, 0) + 1
                elif result and result.get("dead_url"):
                    storage.upsert_ats_endpoint(
                        conn, cid,
                        provider="broken", slug="_dead_url_" + str(cid),
                        status="not_found",
                        open_jobs_actual=0,
                        raw_metadata={"reason": "dns_nxdomain",
                                      "tried": result.get("tried_slugs", [])},
                    )
                    conn.commit()
                    stats["dead_urls"] += 1
                else:
                    storage.upsert_ats_endpoint(
                        conn, cid,
                        provider="unknown", slug="_not_found_" + str(cid),
                        status="not_found",
                        open_jobs_actual=0,
                        raw_metadata={"reason": "no_provider_match"},
                    )
                    conn.commit()
                    stats["misses"] += 1
            except Exception as e:
                log_fh.write(
                    "[" + str(cid) + " " + repr(name) + "] DB upsert failed: "
                    + type(e).__name__ + ": " + str(e) + "\n"
                )
                log_fh.flush()
                stats["errors"] += 1

            if i % 25 == 0:
                print(
                    "  [" + str(i) + "/" + str(len(rows)) + "] "
                    + "hits=" + str(stats["hits"])
                    + " misses=" + str(stats["misses"])
                    + " dead=" + str(stats["dead_urls"])
                    + " err=" + str(stats["errors"])
                )
            _time.sleep(0.4)

        log_fh.write(
            "--- discover_phase end " + datetime.datetime.now().isoformat()
            + " stats=" + str(stats) + " ---\n"
        )
    finally:
        log_fh.close()
    return stats


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ATS Scout: scan ATS APIs and (optionally) discover new endpoints.")
    parser.add_argument("--discover", action="store_true",
                        help="Run discovery (detect ATS for companies without endpoints)")
    parser.add_argument("--then-scan", action="store_true",
                        help="With --discover, also run the scan phase afterward")
    parser.add_argument("--limit", type=int, default=None,
                        help="With --discover, cap companies processed (debugging)")
    parser.add_argument("--max-age-days", type=int, default=30,
                        help="With --discover, retry not_found rows older than this")
    args = parser.parse_args()

    run_scan = (not args.discover) or args.then_scan

    if args.discover:
        sys.path.insert(0, SCRIPTS)
        import storage  # noqa: E402
        if not os.path.exists(DB_PATH):
            print("FATAL: --discover requires SQLite DB at " + DB_PATH)
            sys.exit(1)
        print("Discover phase: starting (max_age_days=" + str(args.max_age_days)
              + ", limit=" + str(args.limit) + ")")
        _conn = storage.connect(DB_PATH)
        try:
            _stats = discover_phase(_conn, limit=args.limit, max_age_days=args.max_age_days)
        finally:
            _conn.close()
        print("Discover phase: done. " + str(_stats))
        if not run_scan:
            sys.exit(0)

    # ============================================================
    # Main scan loop
    # ============================================================

    print("PP Job Scout - ATS API Scan (v2)")
    print("Date: " + str(datetime.date.today()))
    SCAN_COMPANIES, COMPANY_SOURCE = load_companies_from_db()
    print("Company source: " + COMPANY_SOURCE)
    print("Companies: " + str(len(SCAN_COMPANIES)))
    print("Config: " + CONFIG_PATH + " (v" + str(CONFIG.get('_version', '?')) + ")")
    print("JD fallback enabled: " + str(JD_FALLBACK_ENABLED))
    print("-" * 50)

    all_jobs = []
    errors = []
    company_stats = []

    # ============================================================
    # DB connection for direct writes. job_postings is the source of
    # truth; raw_jobs.json is written below as a backup-only artifact.
    # ============================================================
    db_conn = None
    db_jobs_written = 0
    if os.path.exists(DB_PATH):
        sys.path.insert(0, SCRIPTS)
        import storage  # noqa: E402
        db_conn = storage.connect(DB_PATH)
        print("DB writes: ENABLED (" + DB_PATH + ")")
    else:
        print("DB writes: DISABLED (no DB at " + DB_PATH + ")")

    for company in SCAN_COMPANIES:
        ats = company['ats']
        try:
            if ats == 'ashby':
                matches, total = fetch_ashby(company)
            elif ats == 'greenhouse':
                matches, total = fetch_greenhouse(company)
            elif ats == 'lever':
                matches, total = fetch_lever(company)
            else:
                company_stats.append({'company': company['name'], 'ats': 'custom', 'total_jobs': 0, 'matches': 0, 'status': 'skipped'})
                continue
            status = 'ok' if total > 0 else 'empty'
            if total > 0 or len(matches) > 0:
                print("  " + company['name'] + " (" + ats + "): " + str(len(matches)) + " matches / " + str(total) + " total")
            all_jobs.extend(matches)
            company_stats.append({'company': company['name'], 'ats': ats, 'total_jobs': total, 'matches': len(matches), 'status': status})

            # Direct DB write — happens per company so partial failures don't lose data.
            if db_conn is not None and matches:
                endpoint = storage.get_ats_endpoint(db_conn, ats, company['slug'])
                if endpoint is None:
                    print("  WARN: no ats_endpoints row for " + company['name'] + " (" + ats + "/" + company['slug'] + "); skipping DB write")
                else:
                    company_id = endpoint['company_id']
                    endpoint_id = endpoint['id']
                    for j in matches:
                        storage.upsert_job_posting(db_conn, j, company_id=company_id, ats_endpoint_id=endpoint_id)
                        db_jobs_written += 1
                    db_conn.commit()
        except Exception as e:
            errors.append(company['name'] + ": " + str(e))
            print("  " + company['name'] + ": ERROR - " + str(e))
            company_stats.append({'company': company['name'], 'ats': ats, 'total_jobs': 0, 'matches': 0, 'status': 'error'})

    print("-" * 50)
    print("Total potential matches: " + str(len(all_jobs)))

    if all_jobs:
        reason_counts = {}
        for j in all_jobs:
            r = j.get('match_reason', 'unknown')
            reason_counts[r] = reason_counts.get(r, 0) + 1
        print("Match reasons: " + str(reason_counts))

        # Top matched keywords (helps tune config)
        kw_counts = {}
        for j in all_jobs:
            kw = j.get('matched_keyword', '')
            if kw:
                kw_counts[kw] = kw_counts.get(kw, 0) + 1
        top_kw = sorted(kw_counts.items(), key=lambda x: -x[1])[:10]
        print("Top matched keywords: " + str(top_kw))

    broken = [s['company'] for s in company_stats if s['total_jobs'] == 0 and s['status'] not in ('skipped', 'error')]
    if broken:
        print("Companies returning 0 jobs (slug likely wrong): " + str(len(broken)))
        print("  First 20: " + str(broken[:20]))

    if all_jobs:
        sample = all_jobs[0]
        print("Sample posting date: " + str(sample.get('posted_date', 'N/A')) + " (" + str(sample.get('days_ago', '?')) + " days ago)")

    scan_date = str(datetime.date.today())
    scan_method = 'ats_api_direct_v2'
    config_version = CONFIG.get('_version', 'unknown')

    # ============================================================
    # Record scan_run in DB (canonical) + write raw_jobs.json (backup).
    # ============================================================
    if db_conn is not None:
        try:
            storage.add_scan_run(
                db_conn,
                scan_date=scan_date,
                scan_method=scan_method,
                config_version=str(config_version),
                total_companies_scanned=len(SCAN_COMPANIES),
                total_matches=len(all_jobs),
                raw_metadata={
                    'company_stats': company_stats,
                    'errors': errors,
                },
            )
            db_conn.commit()
        finally:
            db_conn.close()
        print("DB writes: " + str(db_jobs_written) + " job_postings upserted, scan_run recorded")

    output = {
        'scan_date': scan_date,
        'scan_method': scan_method,
        'config_version': config_version,
        'total_companies_scanned': len(SCAN_COMPANIES),
        'total_matches': len(all_jobs),
        'company_stats': company_stats,
        'jobs': all_jobs,
        'errors': errors,
        '_note': 'Backup artifact only. job_postings table is canonical.',
    }
    os.makedirs(WORKSPACE, exist_ok=True)
    with open(WORKSPACE + '/raw_jobs.json', 'w') as f:
        json.dump(output, f, indent=2)
    print("Backup written: " + WORKSPACE + "/raw_jobs.json")
