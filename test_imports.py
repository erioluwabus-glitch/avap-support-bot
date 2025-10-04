#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.getcwd())

try:
    from avap_bot.utils.cancel_registry import CancelRegistry
    print("✅ CancelRegistry import successful")
except ImportError as e:
    print(f"❌ CancelRegistry import failed: {e}")

try:
    from avap_bot.utils.cancel_helpers import cooperative_checkpoint
    print("✅ cancel_helpers import successful")
except ImportError as e:
    print(f"❌ cancel_helpers import failed: {e}")

try:
    from avap_bot.features.cancel_feature import get_cancel_fallback_handler
    print("✅ cancel_feature import successful")
except ImportError as e:
    print(f"❌ cancel_feature import failed: {e}")

try:
    import avap_bot.bot
    print("✅ bot import successful")
except ImportError as e:
    print(f"❌ bot import failed: {e}")

print("All imports completed!")
