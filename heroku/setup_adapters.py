"""
Setup module that patches the kodak modules to use PostgreSQL adapters.
This must be imported BEFORE any kodak modules.
"""
import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Add heroku directory to path
heroku_dir = os.path.dirname(os.path.abspath(__file__))
if heroku_dir not in sys.path:
    sys.path.insert(0, heroku_dir)

# Import our adapters
from heroku import db_adapter
from heroku import config_adapter

# Monkey-patch the modules BEFORE they're imported elsewhere
sys.modules['kodak.shared.db'] = db_adapter
sys.modules['kodak.shared.utils'] = config_adapter

# Also provide direct access to commonly used functions
get_connection = db_adapter.get_connection
get_db_connection = db_adapter.get_db_connection
execute_query = db_adapter.execute_query
execute_scalar = db_adapter.execute_scalar
execute_non_query = db_adapter.execute_non_query
execute_batch = db_adapter.execute_batch
query_df = db_adapter.query_df

load_config = config_adapter.load_config
format_local = config_adapter.format_local
clean_num = config_adapter.clean_num

# Mark setup as complete
_ADAPTERS_INITIALIZED = True


def ensure_initialized():
    """Call this to ensure adapters are set up."""
    return _ADAPTERS_INITIALIZED
