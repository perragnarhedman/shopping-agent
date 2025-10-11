import os
from pathlib import Path
from typing import Dict, Any

import yaml


class ConfigLoader:
    @staticmethod
    def load_global_config() -> Dict[str, Any]:
        path = Path('configs/global_config.yaml')
        if not path.exists():
            return {
                'system': {'name': 'Shopping Agent', 'version': '0.1.0', 'environment': os.getenv('ENVIRONMENT', 'development')},
                'logging': {'level': os.getenv('LOG_LEVEL', 'INFO')},
            }
        with path.open('r') as f:
            cfg = yaml.safe_load(f)
        # env overrides
        if 'system' in cfg:
            cfg['system']['environment'] = os.getenv('ENVIRONMENT', cfg['system'].get('environment', 'development'))
        if 'logging' in cfg:
            cfg['logging']['level'] = os.getenv('LOG_LEVEL', cfg['logging'].get('level', 'INFO'))
        # store-specific env overrides
        # COOP_DEFAULT_POSTCODE overrides stores.coop_se.default_postcode if provided
        coop_postcode = os.getenv('COOP_DEFAULT_POSTCODE')
        try:
            if coop_postcode:
                cfg.setdefault('stores', {}).setdefault('coop_se', {})['default_postcode'] = coop_postcode
        except Exception:
            pass
        return cfg


